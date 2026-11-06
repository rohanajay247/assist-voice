// Times and dates as people say them, for text that is read aloud.
// Only the spoken text changes; the text on screen stays as it is.
// "15:00–16:00" -> "3 to 4 pm", "12:00" -> "noon",
// "Mon 30 Nov" -> "Monday the 30th of November".
// Keep in step with scripts/speech.py (both are tested on speech-cases.json).

const DAYS: Record<string, string> = {
  mon: "Monday",
  tue: "Tuesday",
  wed: "Wednesday",
  thu: "Thursday",
  fri: "Friday",
  sat: "Saturday",
  sun: "Sunday",
};
const MONTHS: Record<string, string> = {
  jan: "January",
  feb: "February",
  mar: "March",
  apr: "April",
  may: "May",
  jun: "June",
  jul: "July",
  aug: "August",
  sep: "September",
  oct: "October",
  nov: "November",
  dec: "December",
};

const TIME = String.raw`\b([01]?\d|2[0-3]):([0-5]\d)\b(?:\s*([ap])\.?m\.?\b)?`;
const RANGE = new RegExp(`${TIME}\\s*(?:–|—|-|\\bto\\b)\\s*${TIME}`, "gi");
const SINGLE = new RegExp(TIME, "gi");
const DAY_NAMES = String.raw`(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?,?\s+`;
const MONTH_NAMES = String.raw`(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?`;
const DATE = new RegExp(
  `\\b(?:${DAY_NAMES})?(\\d{1,2})\\s+${MONTH_NAMES}(?![a-z])`,
  "g", // case-sensitive: "3 may be" is not a date
);

type Clock = { h: number; m: number };

// A clock time already in 12-hour form ("3:00 pm") is left alone
function parse(h: string, m: string, suffix?: string): Clock | null {
  const hour = Number(h);
  if (suffix && hour >= 1 && hour <= 12) return null;
  return { h: hour, m: Number(m) };
}

const period = ({ h }: Clock) => (h < 12 ? "am" : "pm");

function bare({ h, m }: Clock): string {
  const hour = h % 12 === 0 ? 12 : h % 12;
  return m ? `${hour}:${String(m).padStart(2, "0")}` : String(hour);
}

function special({ h, m }: Clock): string | null {
  if (m) return null;
  if (h === 12) return "noon";
  if (h === 0) return "midnight";
  return null;
}

function one(c: Clock): string {
  return special(c) ?? `${bare(c)} ${period(c)}`;
}

function range(a: Clock, b: Clock): string {
  if (!special(a) && !special(b) && period(a) === period(b))
    return `${bare(a)} to ${bare(b)} ${period(b)}`;
  return `${one(a)} to ${one(b)}`;
}

function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  return `${n}${{ 1: "st", 2: "nd", 3: "rd" }[n % 10] ?? "th"}`;
}

export function speakable(text: string): string {
  return text
    .replace(RANGE, (all, h1, m1, s1, h2, m2, s2) => {
      const a = parse(h1, m1, s1);
      const b = parse(h2, m2, s2);
      return a && b ? range(a, b) : all;
    })
    .replace(SINGLE, (all, h, m, s) => {
      const c = parse(h, m, s);
      return c ? one(c) : all;
    })
    .replace(DATE, (_all, day: string | undefined, n: string, month: string) => {
      const date = `the ${ordinal(Number(n))} of ${MONTHS[month.slice(0, 3).toLowerCase()]}`;
      return day ? `${DAYS[day.slice(0, 3).toLowerCase()]} ${date}` : date;
    });
}
