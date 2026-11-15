
"use client";

/**
 * ReceivAI UAE — AI Financial Assistant
 * Main authenticated, read-only finance chat interface.
 *
 * Requires:
 * - @/lib/finance-assistant-api
 * - @/components/assistant/AssistantResults
 */

import Link from "next/link";
import AssistantResults from "@/components/assistant/AssistantResults";

import {
  type FormEvent,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  chatWithFinanceAssistant,
  getFinanceAssistantCapabilities,
  getFinanceAssistantSuggestions,
  type FinanceAssistantChatResponse,
  type FinanceAssistantHorizon,
  type FinanceChatHistoryMessage,
  type FinanceSuggestedQuestion,
  FINANCE_ASSISTANT_HORIZONS,
} from "@/lib/finance-assistant-api";

// ============================================================
// TYPES
// ============================================================

type ChatEntry =
  | {
      id: number;
      role: "user";
      content: string;
    }
  | {
      id: number;
      role: "assistant";
      content: string;
      result: FinanceAssistantChatResponse;
    };

// ============================================================
// DEFAULT QUESTIONS
// ============================================================

const STARTER_PROMPTS: FinanceSuggestedQuestion[] = [
  {
    id: "outstanding",
    question: "How much money is outstanding and overdue?",
    category: "receivables_summary",
    description: "Ledger-backed balances",
  },
  {
    id: "overdue",
    question: "Show overdue invoices and their remaining balances",
    category: "overdue_analysis",
    description: "Invoice aging and customer details",
  },
  {
    id: "forecast",
    question: "What are estimated cash collections in the next 30 days?",
    category: "cash_flow_forecast",
    description: "Assumption-based cash-in forecast",
  },
  {
    id: "priorities",
    question: "Which 3 invoices should I prioritize for collections?",
    category: "collection_priorities",
    description: "Existing collection rules",
  },
  {
    id: "reconciliation",
    question: "Are any invoices awaiting payment reconciliation?",
    category: "reconciliation",
    description: "Payment ledger versus register",
  },
  {
    id: "documents",
    question: "Which uploaded documents need review?",
    category: "document_reviews",
    description: "Invoice document processing status",
  },
];

const QUICK_LINKS = [
  {
    href: "/?view=Invoice%20Management",
    label: "Invoices",
    icon: "bi-receipt",
  },
  {
    href: "/collections",
    label: "Collections",
    icon: "bi-wallet2",
  },
  {
    href: "/?view=Cash%20Flow%20Forecast",
    label: "Forecast",
    icon: "bi-graph-up-arrow",
  },
  {
    href: "/documents",
    label: "Documents",
    icon: "bi-file-earmark-text",
  },
];

// ============================================================
// MAIN COMPONENT
// ============================================================

export default function FinanceAssistant() {
  const [question, setQuestion] = useState("");

  const [messages, setMessages] = useState<ChatEntry[]>([]);

  const [horizonDays, setHorizonDays] =
    useState<FinanceAssistantHorizon>(30);

  const [suggestions, setSuggestions] =
    useState<FinanceSuggestedQuestion[]>(STARTER_PROMPTS);

  const [capabilityCount, setCapabilityCount] =
    useState<number | null>(null);

  const [apiReady, setApiReady] =
    useState<boolean | null>(null);

  const [sessionId, setSessionId] =
    useState<string | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const idRef = useRef(0);
  const busyRef = useRef(false);
  const mountedRef = useRef(false);

  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // ==========================================================
  // INITIAL API CAPABILITIES AND SUGGESTIONS
  // ==========================================================

  useEffect(() => {
    mountedRef.current = true;
    let active = true;

    Promise.allSettled([
      getFinanceAssistantSuggestions(),
      getFinanceAssistantCapabilities(),
    ]).then(([questionResponse, capabilityResponse]) => {
      if (!active) return;

      const suggestionsOk =
        questionResponse.status === "fulfilled";

      const capabilitiesOk =
        capabilityResponse.status === "fulfilled";

      setApiReady(suggestionsOk || capabilitiesOk);

      if (
        suggestionsOk &&
        questionResponse.value.suggestions.length > 0
      ) {
        setSuggestions(questionResponse.value.suggestions);
      }

      if (capabilitiesOk) {
        setCapabilityCount(
          capabilityResponse.value.capabilities.filter(
            (item) => item.available,
          ).length,
        );
      }
    });

    return () => {
      active = false;
      mountedRef.current = false;
    };
  }, []);

  // ==========================================================
  // AUTO SCROLL
  // ==========================================================

  useEffect(() => {
    if (messages.length > 0 || busy) {
      const thread = threadRef.current;

      thread?.scrollTo({
        top: thread.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [messages, busy]);

  // ==========================================================
  // SEND QUESTION
  // ==========================================================

  const ask = useCallback(
    async (rawQuestion: string) => {
      if (busyRef.current) return;

      const nextQuestion = rawQuestion.trim();

      if (
        nextQuestion.length < 3 ||
        nextQuestion.length > 2000
      ) {
        setError(
          "Enter a finance question between 3 and 2,000 characters.",
        );
        return;
      }

      // Capture previous history before adding the new question.
      const history: FinanceChatHistoryMessage[] =
        messages.slice(-10).map((message) => ({
          role: message.role,
          content: message.content,
        }));

      const id = ++idRef.current;

      busyRef.current = true;
      setBusy(true);
      setError("");
      setQuestion("");

      setMessages((previous) => [
        ...previous,
        {
          id,
          role: "user",
          content: nextQuestion,
        },
      ]);

      try {
        const result = await chatWithFinanceAssistant({
          question: nextQuestion,
          history,
          horizonDays,
          sessionId,
        });

        if (!mountedRef.current) return;

        setApiReady(true);
        setSessionId(result.session_id ?? null);

        setMessages((previous) => [
          ...previous,
          {
            id: ++idRef.current,
            role: "assistant",
            content: result.answer,
            result,
          },
        ]);
      } catch (cause) {
        if (!mountedRef.current) return;

        // Restore failed question so administrator can retry.
        setMessages((previous) =>
          previous.filter((entry) => entry.id !== id),
        );

        setQuestion(nextQuestion);

        setError(
          cause instanceof Error
            ? cause.message
            : "Unable to reach the Finance Assistant API.",
        );
      } finally {
        busyRef.current = false;

        if (mountedRef.current) {
          setBusy(false);
        }
      }
    },
    [horizonDays, messages, sessionId],
  );

  // ==========================================================
  // FORM ACTIONS
  // ==========================================================

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void ask(question);
  }

  function handleKeyDown(
    event: KeyboardEvent<HTMLTextAreaElement>,
  ) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      void ask(question);
    }
  }

  function clearChat() {
    if (busyRef.current) return;

    setMessages([]);
    setSessionId(null);
    setQuestion("");
    setError("");

    inputRef.current?.focus();
  }

  const promptButtons = suggestions.slice(0, 6);

  // ==========================================================
  // RENDER
  // ==========================================================

  return (
    <section
      className="rfa"
      aria-label="AI Financial Assistant"
    >
      <style>{FINANCE_ASSISTANT_STYLES}</style>

      {/* PAGE HEADING */}

      <header className="rfa-hero">
        <div className="rfa-heading-left">
          <span className="rfa-eyebrow">
            <i
              className="bi bi-stars"
              aria-hidden="true"
            />{" "}
            RECEIVAI INTELLIGENCE / MODULE 04
          </span>

          <div className="rfa-main-heading">
            <span className="rfa-hero-icon">
              <i
                className="bi bi-robot"
                aria-hidden="true"
              />
            </span>

            <div>
              <h1>AI Financial Assistant</h1>
              <p>
                Ask questions across receivables,
                payments, collections and forecasting.
              </p>
            </div>
          </div>
        </div>

        <div className="rfa-hero-status">
          <span
            className={`rfa-status-dot ${
              apiReady === false
                ? "rfa-status-off"
                : ""
            }`}
          />

          {apiReady === null
            ? "Connecting"
            : apiReady
              ? "Assistant API connected"
              : "Connection unavailable"}

          <small>Administrator · Read-only</small>
        </div>
      </header>

      <div className="rfa-workspace">
        {/* MAIN CHAT */}

        <div className="rfa-main">
          <div className="rfa-chat-toolbar">
            <div>
              <strong>
                <i
                  className="bi bi-chat-dots"
                  aria-hidden="true"
                />{" "}
                Finance conversation
              </strong>

              <small>
                Answers are grounded in your recorded
                finance data.
              </small>
            </div>

            <button
              type="button"
              className="rfa-clear"
              onClick={clearChat}
              disabled={
                busy || messages.length === 0
              }
            >
              <i
                className="bi bi-arrow-counterclockwise"
                aria-hidden="true"
              />{" "}
              New chat
            </button>
          </div>

          {/* CHAT MESSAGES */}

          <div
            className="rfa-thread"
            ref={threadRef}
            role="log"
            aria-label="Finance Assistant conversation"
            aria-live="polite"
            aria-relevant="additions"
          >
            {messages.length === 0 && (
              <div className="rfa-welcome">
                <div className="rfa-welcome-icon">
                  <i
                    className="bi bi-stars"
                    aria-hidden="true"
                  />
                </div>

                <h2>
                  What would you like to know
                  about your finances?
                </h2>

                <p>
                  Explore live receivables, check recorded
                  payments, understand collection risks,
                  or review the next cash-in forecast.
                </p>

                <div className="rfa-welcome-prompts">
                  {promptButtons
                    .slice(0, 4)
                    .map((prompt) => (
                      <button
                        key={prompt.id}
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void ask(prompt.question)
                        }
                      >
                        <i
                          className="bi bi-arrow-up-right"
                          aria-hidden="true"
                        />
                        <span>{prompt.question}</span>
                      </button>
                    ))}
                </div>
              </div>
            )}

            {messages.map((message) => (
              <article
                className={`rfa-message rfa-${message.role}`}
                key={message.id}
              >
                <div
                  className="rfa-avatar"
                  aria-hidden="true"
                >
                  <i
                    className={`bi ${
                      message.role === "user"
                        ? "bi-person"
                        : "bi-stars"
                    }`}
                  />
                </div>

                <div className="rfa-message-body">
                  <span className="rfa-sender">
                    {message.role === "user"
                      ? "Administrator"
                      : "ReceivAI Finance Analyst"}
                  </span>

                  <div className="rfa-bubble">
                    <p className="rfa-answer-text">
                      {message.content}
                    </p>

                    {message.role === "assistant" && (
                      <AssistantResults
                        result={message.result}
                        onQuestion={(text) =>
                          void ask(text)
                        }
                        disabled={busy}
                      />
                    )}
                  </div>
                </div>
              </article>
            ))}

            {busy && (
              <div className="rfa-message rfa-assistant">
                <div className="rfa-avatar">
                  <i className="bi bi-stars" />
                </div>

                <div className="rfa-message-body">
                  <span className="rfa-sender">
                    ReceivAI Finance Analyst
                  </span>

                  <div
                    className="rfa-typing"
                    role="status"
                  >
                    <span />
                    <span />
                    <span />
                    Checking finance records…
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* MESSAGE COMPOSER */}

          <div className="rfa-composer-wrap">
            {error && (
              <div
                className="rfa-error"
                role="alert"
              >
                <i
                  className="bi bi-exclamation-triangle"
                  aria-hidden="true"
                />

                <span>{error}</span>

                <button
                  type="button"
                  onClick={() => setError("")}
                  aria-label="Dismiss error"
                >
                  ×
                </button>
              </div>
            )}

            <form
              className="rfa-composer"
              onSubmit={submit}
            >
              <label
                htmlFor="rfa-question"
                className="visually-hidden"
              >
                Ask a financial question
              </label>

              <textarea
                ref={inputRef}
                id="rfa-question"
                rows={2}
                maxLength={2000}
                placeholder="Ask about outstanding invoices, payments, or the next 30 days…"
                value={question}
                disabled={busy}
                onChange={(event) =>
                  setQuestion(event.target.value)
                }
                onKeyDown={handleKeyDown}
              />

              <button
                className="rfa-send"
                type="submit"
                disabled={
                  busy ||
                  question.trim().length < 3
                }
                aria-label="Send finance question"
              >
                <i
                  className={`bi ${
                    busy
                      ? "bi-hourglass-split"
                      : "bi-arrow-up"
                  }`}
                  aria-hidden="true"
                />
              </button>
            </form>

            <div className="rfa-composer-caption">
              <span>
                <i
                  className="bi bi-shield-lock"
                  aria-hidden="true"
                />{" "}
                Admin-only · No automatic financial changes
              </span>

              <span>
                Enter to send · Shift+Enter for a new line
              </span>
            </div>
          </div>
        </div>

        {/* RIGHT SIDEBAR */}

        <aside
          className="rfa-side"
          aria-label="Assistant shortcuts and settings"
        >
          {/* FORECAST PERIOD */}

          <div className="rfa-side-card">
            <div className="rfa-side-card-title">
              <i
                className="bi bi-calendar-range"
                aria-hidden="true"
              />{" "}
              Forecast period
            </div>

            <p>
              Choose the default horizon for
              forecast questions.
            </p>

            <div
              className="rfa-horizon-grid"
              role="group"
              aria-label="Forecast period in days"
            >
              {FINANCE_ASSISTANT_HORIZONS.map(
                (days) => (
                  <button
                    type="button"
                    key={days}
                    className={
                      horizonDays === days
                        ? "active"
                        : ""
                    }
                    disabled={busy}
                    aria-pressed={
                      horizonDays === days
                    }
                    onClick={() =>
                      setHorizonDays(days)
                    }
                  >
                    {days}d
                  </button>
                ),
              )}
            </div>

            <small>
              Estimated receipts, not guaranteed
              bank deposits.
            </small>
          </div>

          {/* QUICK QUESTIONS */}

          <div className="rfa-side-card">
            <div className="rfa-side-card-title">
              <i
                className="bi bi-lightning-charge"
                aria-hidden="true"
              />{" "}
              Quick questions
            </div>

            <div className="rfa-side-prompts">
              {promptButtons.map((prompt) => (
                <button
                  key={prompt.id}
                  type="button"
                  onClick={() =>
                    void ask(prompt.question)
                  }
                  disabled={busy}
                  title={
                    prompt.description ||
                    undefined
                  }
                >
                  <span>{prompt.question}</span>
                  <i
                    className="bi bi-chevron-right"
                    aria-hidden="true"
                  />
                </button>
              ))}
            </div>
          </div>

          {/* WORKSPACE NAVIGATION */}

          <div className="rfa-side-card">
            <div className="rfa-side-card-title">
              <i
                className="bi bi-grid"
                aria-hidden="true"
              />{" "}
              Your finance workspace
            </div>

            <div className="rfa-links">
              {QUICK_LINKS.map((item) => (
                <Link
                  href={item.href}
                  key={item.href}
                >
                  <i
                    className={`bi ${item.icon}`}
                    aria-hidden="true"
                  />{" "}
                  {item.label}

                  <i
                    className="bi bi-arrow-up-right"
                    aria-hidden="true"
                  />
                </Link>
              ))}
            </div>
          </div>

          {/* PRIVACY NOTICE */}

          <div className="rfa-safety">
            <i
              className="bi bi-shield-check"
              aria-hidden="true"
            />

            <div>
              <strong>
                Privacy-first financial analysis
              </strong>

              <p>
                Uses existing authorized backend services.
                Payment entries are not independently
                bank-verified; forecasts use documented
                assumptions. Chat history is only held
                in this open page.
              </p>

              {capabilityCount !== null && (
                <small>
                  {capabilityCount} financial analysis
                  capabilities available
                </small>
              )}
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}

// ============================================================
// STYLES
// ============================================================

const FINANCE_ASSISTANT_STYLES = `
.rfa {
  color: #0F1B2D;
  font-family: inherit;
  width: 100%;
}
.rfa * {
  box-sizing: border-box;
}
.rfa button,
.rfa textarea {
  font: inherit;
}
.rfa button:focus-visible,
.rfa a:focus-visible,
.rfa textarea:focus-visible {
  outline: 3px solid #88b7ff;
  outline-offset: 3px;
}
.rfa-hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  padding: 8px 0 24px;
}
.rfa-eyebrow {
  color: #2463D4;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 1.6px;
}
.rfa-main-heading {
  display: flex;
  align-items: center;
  gap: 15px;
  margin-top: 12px;
}
.rfa-hero-icon {
  width: 56px;
  height: 56px;
  border-radius: 17px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #2463D4, #7048C8);
  color: #fff;
  flex-shrink: 0;
  font-size: 25px;
  box-shadow: 0 12px 28px rgba(36,99,212,.18);
}
.rfa-hero h1 {
  font-size: clamp(24px, 2.4vw, 32px);
  margin: 0 0 5px;
  font-weight: 800;
  letter-spacing: -.7px;
}
.rfa-hero p {
  font-size: 13px;
  color: #66758A;
  margin: 0;
}
.rfa-hero-status {
  border: 1px solid #DCE3EC;
  background: #fff;
  border-radius: 13px;
  padding: 11px 14px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}
.rfa-hero-status small {
  display: block;
  margin-left: 16px;
  font-size: 10px;
  font-weight: 500;
  color: #66758A;
  padding-top: 3px;
}
.rfa-status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 7px;
  background: #22a06b;
}
.rfa-status-off {
  background: #d97706;
}
.rfa-workspace {
  display: grid;
  grid-template-columns: minmax(0,1fr) 278px;
  gap: 20px;
  align-items: start;
}
.rfa-main {
  background: #fff;
  border: 1px solid #DCE3EC;
  border-radius: 17px;
  box-shadow: 0 9px 32px rgba(15,27,45,.04);
  min-width: 0;
  overflow: hidden;
}
.rfa-chat-toolbar {
  padding: 19px 22px;
  border-bottom: 1px solid #E8EDF4;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.rfa-chat-toolbar strong {
  display: block;
  font-size: 14px;
  font-weight: 800;
}
.rfa-chat-toolbar strong i {
  color: #7048C8;
  margin-right: 8px;
}
.rfa-chat-toolbar small {
  display: block;
  color: #66758A;
  font-size: 11px;
  margin-top: 4px;
}
.rfa-clear {
  border: 1px solid #DCE3EC;
  color: #425166;
  background: #fff;
  border-radius: 9px;
  padding: 8px 11px;
  font-weight: 700;
  font-size: 11px;
  white-space: nowrap;
}
.rfa-clear:hover:not(:disabled) {
  border-color: #2463D4;
  color: #2463D4;
}
.rfa button:disabled {
  opacity: .52;
  cursor: not-allowed;
}
.rfa-thread {
  height: min(58vh,620px);
  min-height: 380px;
  overflow: auto;
  padding: 23px 22px 30px;
  background: linear-gradient(180deg,#fff 0%,#fbfcff 100%);
}
.rfa-welcome {
  max-width: 660px;
  margin: 32px auto 20px;
  text-align: center;
}
.rfa-welcome-icon {
  display: grid;
  place-items: center;
  width: 60px;
  height: 60px;
  margin: 0 auto 17px;
  background: #F1ECFA;
  color: #7048C8;
  border-radius: 19px;
  font-size: 26px;
}
.rfa-welcome h2 {
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -.4px;
  margin: 0 0 8px;
}
.rfa-welcome p {
  color: #66758A;
  font-size: 13px;
  line-height: 1.7;
  max-width: 465px;
  margin: 0 auto 24px;
}
.rfa-welcome-prompts {
  display: grid;
  grid-template-columns: repeat(2,minmax(0,1fr));
  gap: 10px;
  text-align: left;
}
.rfa-welcome-prompts button {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  border: 1px solid #DCE3EC;
  border-radius: 11px;
  background: #fff;
  padding: 13px;
  text-align: left;
  color: #425166;
  font-size: 12px;
  font-weight: 650;
  line-height: 1.45;
}
.rfa-welcome-prompts button i {
  color: #2463D4;
}
.rfa-welcome-prompts button:hover:not(:disabled) {
  background: #F7F9FC;
  border-color: #b9cdeb;
}
.rfa-message {
  display: flex;
  gap: 12px;
  margin: 0 0 20px;
  max-width: 100%;
}
.rfa-user {
  justify-content: flex-end;
}
.rfa-avatar {
  width: 31px;
  height: 31px;
  display: grid;
  place-items: center;
  flex: 0 0 31px;
  border-radius: 10px;
  background: #F1ECFA;
  color: #7048C8;
}
.rfa-user .rfa-avatar {
  background: #E7F0FC;
  color: #2463D4;
  order: 2;
}
.rfa-message-body {
  min-width: 0;
  max-width: 100%;
  width: 100%;
}
.rfa-user .rfa-message-body {
  width: auto;
  max-width: 85%;
  text-align: right;
}
.rfa-sender {
  font-size: 10px;
  font-weight: 700;
  color: #66758A;
  display: block;
  margin-bottom: 7px;
}
.rfa-bubble {
  background: #fff;
  border: 1px solid #E3E8F0;
  border-radius: 4px 14px 14px 14px;
  padding: 15px;
  box-shadow: 0 3px 11px rgba(15,27,45,.03);
  text-align: left;
}
.rfa-user .rfa-bubble {
  background: #2463D4;
  color: #fff;
  border-color: #2463D4;
  border-radius: 14px 4px 14px 14px;
}
.rfa-answer-text {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.7;
  font-size: 13px;
  overflow-wrap: anywhere;
}
.rfa-answer-details {
  margin-top: 16px;
}
.rfa-metric-grid {
  display: grid;
  grid-template-columns: repeat(2,minmax(0,1fr));
  gap: 10px;
  margin-bottom: 15px;
}
.rfa-metric {
  background: #F7F9FC;
  border: 1px solid #E2E8F1;
  border-radius: 11px;
  padding: 13px;
  min-width: 0;
}
.rfa-metric-label {
  display: block;
  color: #66758A;
  font-size: 11px;
  font-weight: 600;
}
.rfa-metric strong {
  display: block;
  color: #0F1B2D;
  font-size: clamp(15px,1.5vw,19px);
  font-weight: 800;
  letter-spacing: -.3px;
  margin: 6px 0 4px;
  overflow-wrap: anywhere;
}
.rfa-metric-meta {
  font-size: 10px;
  color: #66758A;
  line-height: 1.4;
  display: block;
}
.rfa-table-card {
  border: 1px solid #DCE3EC;
  border-radius: 11px;
  margin: 0 0 14px;
  overflow: hidden;
  background: #fff;
}
.rfa-table-title {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  padding: 13px 14px;
}
.rfa-table-title strong {
  font-size: 12px;
}
.rfa-table-title span {
  background: #EEF3F8;
  color: #66758A;
  border-radius: 999px;
  padding: 4px 8px;
  font-size: 10px;
}
.rfa-table-desc {
  font-size: 11px;
  color: #66758A;
  margin: 0;
  padding: 0 14px 10px;
}
.rfa-table-scroll {
  overflow-x: auto;
}
.rfa-table-card table {
  width: 100%;
  border-collapse: collapse;
  min-width: 370px;
  font-size: 11px;
}
.rfa-table-card th {
  background: #F7F9FC;
  color: #66758A;
  padding: 10px;
  text-align: left;
  font-weight: 750;
  white-space: nowrap;
  border-block: 1px solid #E7ECF3;
}
.rfa-table-card td {
  padding: 10px;
  border-bottom: 1px solid #F0F3F8;
  vertical-align: top;
  overflow-wrap: anywhere;
}
.rfa-money {
  white-space: nowrap;
  font-weight: 700;
}
.rfa-table-empty {
  text-align: center;
  color: #66758A;
}
.rfa-table-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  color: #66758A;
  font-size: 10px;
}
.rfa-text-button {
  background: none;
  border: 0;
  color: #2463D4;
  font-weight: 800;
  font-size: 11px;
}
.rfa-linked-invoices {
  margin-bottom: 14px;
}
.rfa-linked-invoices > strong {
  display: block;
  font-size: 12px;
  margin-bottom: 9px;
}
.rfa-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.rfa-link-chip,
.rfa-prompt-chip,
.rfa-action-link {
  display: inline-flex;
  gap: 7px;
  align-items: center;
  text-decoration: none;
  background: #F7F9FC;
  border: 1px solid #DCE3EC;
  border-radius: 8px;
  color: #425166;
  font-size: 11px;
  padding: 8px 10px;
  line-height: 1.4;
}
.rfa-link-chip:hover,
.rfa-action-link:hover,
.rfa-prompt-chip:hover {
  color: #2463D4;
  border-color: #aac7f3;
  background: #F4F8FF;
}
.rfa-muted {
  display: block;
  color: #66758A;
  font-size: 10px;
  margin-top: 7px;
}
.rfa-insight-list {
  margin: 10px 0 13px;
  display: grid;
  gap: 9px;
}
.rfa-insight {
  display: flex;
  gap: 10px;
  border-left: 3px solid #2463D4;
  background: #F3F7FD;
  border-radius: 8px;
  padding: 12px;
  font-size: 11px;
}
.rfa-insight-warning {
  border-color: #e2a335;
  background: #fff9ec;
}
.rfa-insight-critical {
  border-color: #db5d66;
  background: #fff2f3;
}
.rfa-insight > i {
  margin-top: 2px;
  color: #2463D4;
}
.rfa-insight-warning > i {
  color: #b47c19;
}
.rfa-insight-critical > i {
  color: #b92f3c;
}
.rfa-insight strong {
  display: block;
  font-size: 12px;
  margin-bottom: 4px;
}
.rfa-insight p {
  color: #425166;
  margin: 0 0 4px;
  line-height: 1.55;
}
.rfa-insight small {
  color: #66758A;
  line-height: 1.55;
  display: block;
}
.rfa-warnings {
  display: flex;
  gap: 8px;
  border: 1px solid #f3deb2;
  background: #fff9ee;
  border-radius: 10px;
  color: #825a0c;
  padding: 11px;
  font-size: 11px;
  margin: 10px 0;
}
.rfa-warnings p {
  margin: 0 0 6px;
}
.rfa-warnings p:last-child {
  margin-bottom: 0;
}
.rfa-action-row {
  margin: 13px 0;
}
.rfa-action-link {
  background: #E7F0FC;
  color: #174EA6;
  border-color: #C7D9F7;
  font-weight: 800;
}
.rfa-followups {
  border-top: 1px solid #E8EDF4;
  padding-top: 13px;
  margin-top: 12px;
}
.rfa-followups > span {
  display: block;
  font-size: 10px;
  color: #66758A;
  margin-bottom: 8px;
  font-weight: 750;
}
.rfa-prompt-chip {
  cursor: pointer;
  background: #fff;
}
.rfa-evidence-footer {
  display: flex;
  align-items: start;
  gap: 7px;
  font-size: 10px;
  color: #66758A;
  border-top: 1px solid #E8EDF4;
  padding-top: 12px;
  margin-top: 13px;
  line-height: 1.5;
}
.rfa-evidence-footer i {
  color: #2f9a78;
  margin-top: 1px;
}
.rfa-typing {
  display: flex;
  gap: 5px;
  align-items: center;
  font-size: 11px;
  color: #66758A;
  background: #F7F9FC;
  padding: 13px;
  border-radius: 10px;
  max-width: max-content;
}
.rfa-typing span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #2463D4;
  animation: rfa-blink 1s infinite alternate;
}
.rfa-typing span:nth-child(2) {
  animation-delay: .2s;
}
.rfa-typing span:nth-child(3) {
  animation-delay: .4s;
  margin-right: 6px;
}
@keyframes rfa-blink {
  to {
    opacity: .2;
    transform: translateY(-3px);
  }
}
.rfa-composer-wrap {
  border-top: 1px solid #E8EDF4;
  padding: 14px 18px;
  background: #fff;
}
.rfa-composer {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  border: 1px solid #C9D5E4;
  border-radius: 12px;
  background: #fff;
  padding: 7px 7px 7px 13px;
}
.rfa-composer:focus-within {
  border-color: #2463D4;
  box-shadow: 0 0 0 3px rgba(36,99,212,.08);
}
.rfa-composer textarea {
  border: 0;
  resize: vertical;
  min-height: 50px;
  max-height: 150px;
  width: 100%;
  flex: 1;
  outline: 0;
  padding: 7px 2px;
  background: transparent;
  font-size: 13px;
  color: #0F1B2D;
  line-height: 1.6;
}
.rfa-composer textarea:focus {
  outline: 0;
}
.rfa-composer textarea::placeholder {
  color: #8695A8;
}
.rfa-send {
  border: 0;
  border-radius: 9px;
  background: #2463D4;
  width: 40px;
  height: 40px;
  color: #fff;
  font-size: 18px;
  flex-shrink: 0;
}
.rfa-send:hover:not(:disabled) {
  background: #174EA6;
}
.rfa-composer-caption {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 3px 0;
  font-size: 10px;
  color: #718096;
}
.rfa-composer-caption i {
  color: #377e6a;
}
.rfa-error {
  display: flex;
  gap: 10px;
  align-items: center;
  border: 1px solid #f0c6ca;
  background: #fff2f3;
  color: #a72837;
  border-radius: 9px;
  padding: 10px 12px;
  margin-bottom: 10px;
  font-size: 12px;
}
.rfa-error span {
  flex: 1;
  overflow-wrap: anywhere;
}
.rfa-error button {
  border: 0;
  background: transparent;
  font-size: 20px;
  color: inherit;
}
.rfa-side {
  display: grid;
  gap: 14px;
}
.rfa-side-card {
  background: #fff;
  border: 1px solid #DCE3EC;
  border-radius: 14px;
  padding: 18px;
  box-shadow: 0 8px 26px rgba(15,27,45,.025);
}
.rfa-side-card-title {
  display: flex;
  gap: 9px;
  align-items: center;
  font-size: 13px;
  font-weight: 800;
}
.rfa-side-card-title i {
  color: #2463D4;
  font-size: 15px;
}
.rfa-side-card p {
  color: #66758A;
  font-size: 11px;
  line-height: 1.6;
  margin: 9px 0 12px;
}
.rfa-side-card > small {
  color: #66758A;
  font-size: 10px;
  line-height: 1.5;
  display: block;
  margin-top: 11px;
}
.rfa-horizon-grid {
  display: grid;
  grid-template-columns: repeat(4,minmax(0,1fr));
  gap: 6px;
}
.rfa-horizon-grid button {
  border: 1px solid #DCE3EC;
  border-radius: 8px;
  background: #fff;
  font-size: 11px;
  padding: 9px 2px;
  color: #425166;
  font-weight: 800;
}
.rfa-horizon-grid button.active {
  background: #2463D4;
  color: #fff;
  border-color: #2463D4;
}
.rfa-side-prompts {
  display: grid;
  gap: 3px;
  margin-top: 11px;
}
.rfa-side-prompts button {
  display: flex;
  justify-content: space-between;
  align-items: start;
  gap: 9px;
  background: none;
  border: 0;
  text-align: left;
  color: #425166;
  padding: 10px 4px;
  border-bottom: 1px solid #EEF1F6;
  font-size: 11px;
  line-height: 1.5;
}
.rfa-side-prompts button:last-child {
  border-bottom: 0;
}
.rfa-side-prompts button:hover:not(:disabled) {
  color: #2463D4;
}
.rfa-side-prompts button i {
  color: #93A0B3;
  font-size: 10px;
  padding-top: 3px;
}
.rfa-links {
  display: grid;
  gap: 4px;
  margin-top: 11px;
}
.rfa-links a {
  display: flex;
  align-items: center;
  gap: 9px;
  text-decoration: none;
  font-size: 11px;
  color: #425166;
  padding: 9px 7px;
  border-radius: 8px;
}
.rfa-links a:hover {
  background: #F7F9FC;
  color: #2463D4;
}
.rfa-links a i:last-child {
  margin-left: auto;
  color: #90A0B5;
}
.rfa-safety {
  display: flex;
  gap: 11px;
  border: 1px solid #DDE7F6;
  background: #EEF3F8;
  border-radius: 13px;
  padding: 15px;
}
.rfa-safety > i {
  color: #2463D4;
}
.rfa-safety strong {
  display: block;
  font-size: 11px;
}
.rfa-safety p {
  color: #66758A;
  font-size: 10px;
  line-height: 1.6;
  margin: 7px 0;
}
.rfa-safety small {
  color: #425166;
  font-size: 10px;
}

@media (max-width: 1150px) {
  .rfa-workspace {
    grid-template-columns: minmax(0,1fr) 245px;
    gap: 13px;
  }
  .rfa-side-card {
    padding: 14px;
  }
}
@media (max-width: 950px) {
  .rfa-workspace {
    grid-template-columns: 1fr;
  }
  .rfa-side {
    grid-template-columns: repeat(2,minmax(0,1fr));
  }
  .rfa-safety {
    grid-column: 1 / -1;
  }
  .rfa-thread {
    height: 52vh;
  }
}
@media (max-width: 620px) {
  .rfa-hero {
    align-items: flex-start;
    flex-direction: column;
    gap: 13px;
  }
  .rfa-hero-status {
    white-space: normal;
  }
  .rfa-chat-toolbar {
    padding: 14px;
  }
  .rfa-thread {
    padding: 17px 12px;
    min-height: 330px;
  }
  .rfa-welcome-prompts,
  .rfa-metric-grid,
  .rfa-side {
    grid-template-columns: 1fr;
  }
  .rfa-hero-icon {
    width: 46px;
    height: 46px;
  }
  .rfa-welcome h2 {
    font-size: 19px;
  }
  .rfa-side {
    gap: 10px;
  }
  .rfa-safety {
    grid-column: auto;
  }
  .rfa-user .rfa-message-body {
    max-width: 90%;
  }
  .rfa-composer-wrap {
    padding: 11px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .rfa-typing span {
    animation: none;
  }
}
`;
