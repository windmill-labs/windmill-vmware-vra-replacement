import tls from "node:tls";

// Check the TLS certificate of each endpoint and fail when one expires within
// warn_days. Failing the job is the alert: the schedule's error handler (or the
// workspace error handler) sends it to Slack, Teams, email or a pager.

async function inspect(target: string, timeoutMs: number) {
  const [host, portStr] = target.split(":");
  const port = Number(portStr || 443);
  return await new Promise<{ target: string; expires: string; days_left: number; subject: string }>(
    (resolve, reject) => {
      const socket = tls.connect({ host, port, servername: host, rejectUnauthorized: false }, () => {
        const cert = socket.getPeerCertificate();
        socket.end();
        if (!cert || !cert.valid_to) return reject(new Error(`${target}: no certificate`));
        const expires = new Date(cert.valid_to);
        resolve({
          target,
          expires: expires.toISOString(),
          days_left: Math.floor((expires.getTime() - Date.now()) / 86_400_000),
          subject: String(cert.subject?.CN ?? ""),
        });
      });
      socket.setTimeout(timeoutMs, () => {
        socket.destroy();
        reject(new Error(`${target}: timeout`));
      });
      socket.on("error", (e) => reject(new Error(`${target}: ${e.message}`)));
    },
  );
}

export async function main(endpoints: string[], warn_days: number = 21, timeout_ms: number = 5000) {
  const settled = await Promise.allSettled(endpoints.map((e) => inspect(e, timeout_ms)));
  const checked = settled.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
  const unreachable = settled.flatMap((r) => (r.status === "rejected" ? [String(r.reason?.message ?? r.reason)] : []));
  const expiring = checked.filter((c) => c.days_left <= warn_days).sort((a, b) => a.days_left - b.days_left);

  if (expiring.length > 0 || unreachable.length > 0) {
    const lines = [
      ...expiring.map((c) => `${c.target} expires in ${c.days_left} days (${c.expires.slice(0, 10)})`),
      ...unreachable.map((u) => `unreachable: ${u}`),
    ];
    throw new Error(`Certificate check failed:\n${lines.join("\n")}`);
  }
  return { checked: checked.length, soonest: checked.sort((a, b) => a.days_left - b.days_left)[0] ?? null };
}
