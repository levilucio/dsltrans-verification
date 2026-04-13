async function request(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

async function requestStream(path, payload, onEvent) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let data = null;
    try {
      data = await response.json();
    } catch (_) {
      // Ignore parse failure and fall back to generic message.
    }
    throw new Error(data?.error || "Request failed");
  }
  if (!response.body) {
    throw new Error("Streaming response is not available");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalEvent = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      const event = JSON.parse(trimmed);
      onEvent?.(event);
      if (event.event === "error") {
        throw new Error(event.error || "Streaming request failed");
      }
      if (event.event === "complete") {
        finalEvent = event;
      }
    }
  }

  if (buffer.trim()) {
    const event = JSON.parse(buffer.trim());
    onEvent?.(event);
    if (event.event === "error") {
      throw new Error(event.error || "Streaming request failed");
    }
    if (event.event === "complete") {
      finalEvent = event;
    }
  }

  if (!finalEvent) {
    throw new Error("Streaming request ended before completion");
  }
  return finalEvent;
}

export function runConcrete(payload) {
  return request("/api/dsltrans/run/concrete", payload);
}

export function runExplore(payload) {
  return request("/api/dsltrans/run/explore", payload);
}

export function runSmtDirect(payload) {
  return request("/api/dsltrans/run/smt_direct", payload);
}

export function runSmtDirectStream(payload, onEvent) {
  return requestStream("/api/dsltrans/run/smt_direct_stream", payload, onEvent);
}

export function runCutoff(payload) {
  return request("/api/dsltrans/run/cutoff", payload);
}

export function parseSpec(payload) {
  return request("/api/dsltrans/parse", payload);
}

export function validateFragment(payload) {
  return request("/api/dsltrans/validate_fragment", payload);
}
