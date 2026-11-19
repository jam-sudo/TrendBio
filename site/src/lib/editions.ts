export const editions = ["physics", "biology"] as const;
export type Edition = typeof editions[number];
