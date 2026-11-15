
"use client";

import { useEffect, useState } from "react";

/**
 * ReceivAI UAE — Dynamic UAE Greeting
 *
 * Uses Dubai local time (Asia/Dubai) instead of
 * the computer's selected timezone.
 *
 * Refreshes every minute and when the tab becomes visible.
 */

function greetingInDubai(now: Date = new Date()): string {
  const hourPart = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Dubai",
    hour: "2-digit",
    hourCycle: "h23",
  })
    .formatToParts(now)
    .find((part) => part.type === "hour");

  const hour = hourPart ? Number(hourPart.value) : NaN;

  if (!Number.isInteger(hour)) {
    return "Hello";
  }

  if (hour >= 5 && hour < 12) {
    return "Good morning";
  }

  if (hour >= 12 && hour < 17) {
    return "Good afternoon";
  }

  return "Good evening";
}

export interface UaeGreetingProps {
  name?: string;
}

export default function UaeGreeting({
  name = "Administrator",
}: UaeGreetingProps) {
  const [greeting, setGreeting] = useState("Hello");

  useEffect(() => {
    const refresh = () => {
      setGreeting(greetingInDubai());
    };

    refresh();

    const intervalId = window.setInterval(
      refresh,
      60_000,
    );

    document.addEventListener(
      "visibilitychange",
      refresh,
    );

    return () => {
      window.clearInterval(intervalId);

      document.removeEventListener(
        "visibilitychange",
        refresh,
      );
    };
  }, []);

  return (
    <>
      {greeting}, {name}
    </>
  );
}
