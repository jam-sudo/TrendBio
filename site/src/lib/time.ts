const eastern = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York", month: "short", day: "numeric", year: "numeric",
  hour: "numeric", minute: "2-digit", hour12: false, timeZoneName: "short",
});

export const formatEastern = (iso: string) => eastern.format(new Date(iso));
