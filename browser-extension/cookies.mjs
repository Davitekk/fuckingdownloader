export function netscapeCookies(cookies) {
  const rows = [];
  for (const cookie of cookies) {
    const domain = cookie.domain.replace(/^\./, "").toLowerCase();
    if ((domain !== "tiktok.com" && !domain.endsWith(".tiktok.com")) || cookie.partitionKey) {
      continue;
    }
    const fields = [
      (cookie.httpOnly ? "#HttpOnly_" : "") + cookie.domain,
      cookie.hostOnly ? "FALSE" : "TRUE",
      cookie.path,
      cookie.secure ? "TRUE" : "FALSE",
      String(Math.floor(cookie.expirationDate ?? 0)),
      cookie.name,
      cookie.value,
    ];
    if (fields.every((field) => !/[\t\r\n\0]/.test(field))) {
      rows.push(fields.join("\t"));
    }
  }
  return rows.length ? "# Netscape HTTP Cookie File\n" + rows.join("\n") + "\n" : null;
}
