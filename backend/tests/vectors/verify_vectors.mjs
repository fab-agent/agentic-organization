// Independent JS check of the ADR-0027 vectors (canonical bytes, Ed25519 signatures, domain
// separation, digest). Run by tests/test_workspace_manifest.py when node is available.
import fs from "node:fs";
import crypto from "node:crypto";
const v = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));

// Independent implementation of the canonical profile (ADR-0027), written from the spec.
function esc(s) {
  let out = '"';
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c === 0x22) out += '\\"';
    else if (c === 0x5c) out += "\\\\";
    else if (c === 0x08) out += "\\b";
    else if (c === 0x09) out += "\\t";
    else if (c === 0x0a) out += "\\n";
    else if (c === 0x0c) out += "\\f";
    else if (c === 0x0d) out += "\\r";
    else if (c >= 0x20 && c <= 0x7e) out += s[i];
    else out += "\\u" + c.toString(16).padStart(4, "0");
  }
  return out + '"';
}
function ser(x) {
  if (x === null) return "null";
  if (x === true) return "true";
  if (x === false) return "false";
  if (typeof x === "string") return esc(x);
  if (typeof x === "number") {
    if (!Number.isSafeInteger(x)) throw new Error("unsafe");
    return String(x);
  }
  if (Array.isArray(x)) return "[" + x.map(ser).join(",") + "]";
  // default JS string comparison is UTF-16 code unit order
  const keys = Object.keys(x).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  return "{" + keys.map((k) => esc(k) + ":" + ser(x[k])).join(",") + "}";
}
let bad = 0;
for (const c of v.canonical) {
  const got = ser(c.input);
  if (got !== c.bytes) { bad++; console.log("CANON MISMATCH", JSON.stringify(c.input), got, c.bytes); }
}
console.log("canonical cases:", v.canonical.length, "mismatches:", bad);

// Ed25519 verification of cert, manifest and CRL with node:crypto.
const spki = (b64) => crypto.createPublicKey({ key: Buffer.concat([Buffer.from("302a300506032b6570032100", "hex"), Buffer.from(b64, "base64")]), format: "der", type: "spki" });
const dom = { cert: "fab-signing-cert-v1\n", crl: "fab-crl-v1\n", manifest: "fab-workspace-manifest-v1\n" };
const check = (kind, pubB64, doc, sigB64) =>
  crypto.verify(null, Buffer.from(dom[kind] + ser(doc), "ascii"), spki(pubB64), Buffer.from(sigB64, "base64"));
const r = {
  cert: check("cert", v.root_pub, v.cert.payload, v.cert.sig),
  manifest: check("manifest", v.cert.payload.pub, v.manifest.payload, v.manifest.sig),
  crl: check("crl", v.root_pub, v.crl.payload, v.crl.sig),
  // domain separation: a manifest signature must NOT verify as a cert
  separation: !check("cert", v.root_pub, v.manifest.payload, v.manifest.sig),
  digest: crypto.createHash("sha256").update(ser(v.manifest.payload)).digest("hex") === v.manifest_digest,
};
console.log(JSON.stringify(r));
process.exit(bad || Object.values(r).some((x) => !x) ? 1 : 0);
