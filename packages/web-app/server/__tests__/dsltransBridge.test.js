import { EventEmitter } from "events";

jest.mock("child_process", () => ({
  spawn: jest.fn(),
}));

import { spawn } from "child_process";
import { parseDsltransSpec, streamDsltransSmtDirect } from "../dsltransBridge.js";

function fakeProc(output = { ok: true }) {
  const proc = new EventEmitter();
  proc.stdout = new EventEmitter();
  proc.stderr = new EventEmitter();
  proc.stdin = { write: jest.fn(), end: jest.fn() };
  setTimeout(() => {
    proc.stdout.emit("data", JSON.stringify(output));
    proc.emit("close", 0);
  }, 0);
  return proc;
}

function fakeStreamingProc(lines = []) {
  const proc = new EventEmitter();
  proc.stdout = new EventEmitter();
  proc.stderr = new EventEmitter();
  proc.stdin = { write: jest.fn(), end: jest.fn() };
  setTimeout(() => {
    for (const line of lines) {
      proc.stdout.emit("data", `${JSON.stringify(line)}\n`);
    }
    proc.emit("close", 0);
  }, 0);
  return proc;
}

describe("dsltransBridge", () => {
  test("returns parsed JSON from python bridge", async () => {
    spawn.mockImplementation(() => fakeProc({ transformations: ["T1"] }));
    const result = await parseDsltransSpec({ specText: "dsltransformation" });
    expect(result.transformations).toEqual(["T1"]);
  });

  test("streams proof progress events from python bridge", async () => {
    const events = [];
    spawn.mockImplementation(() =>
      fakeStreamingProc([
        { event: "start", total: 2 },
        { event: "property_result", completed: 1, remaining: 1, result: { property: "P1", result: "HOLDS" } },
        { event: "complete", completed: 2, remaining: 0, results: [{ property: "P1", result: "HOLDS" }] },
      ]),
    );

    await new Promise((resolve, reject) => {
      streamDsltransSmtDirect(
        { specText: "dsltransformation" },
        {
          onEvent: (event) => events.push(event),
          onError: reject,
          onClose: resolve,
        },
      );
    });

    expect(events.map((event) => event.event)).toEqual(["start", "property_result", "complete"]);
    expect(events[1].result.property).toBe("P1");
  });
});
