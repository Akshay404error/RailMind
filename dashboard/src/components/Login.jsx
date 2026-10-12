import { useEffect, useState } from "react";
import { requestOtp, verifyOtp, registerUser, setToken } from "../auth";

// Steps: "email" -> "code" -> ("details" if new user) -> onLogin(user)
export default function Login({ onLogin }) {
  const [step, setStep] = useState("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [signupToken, setSignupToken] = useState("");
  const [details, setDetails] = useState({ name: "", phone: "", role: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown(cooldown - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  async function run(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const sendCode = () =>
    run(async () => {
      await requestOtp(email);
      setStep("code");
      setCooldown(30);
    });

  const checkCode = () =>
    run(async () => {
      const r = await verifyOtp(email, code);
      if (r.new_user) {
        setSignupToken(r.signup_token);
        setStep("details");
      } else {
        setToken(r.token);
        onLogin(r.user);
      }
    });

  const finishSignup = () =>
    run(async () => {
      const r = await registerUser(signupToken, details);
      setToken(r.token);
      onLogin(r.user);
    });

  const set = (k) => (e) => setDetails({ ...details, [k]: e.target.value });

  return (
    <div className="login-wrap">
      <div className="login-card">
        <h1>RailMind</h1>
        <p className="login-sub">Sign in with a one-time code sent to your email</p>

        {step === "email" && (
          <>
            <input
              type="email"
              placeholder="you@gmail.com"
              value={email}
              autoFocus
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && email && sendCode()}
            />
            <button disabled={busy || !email} onClick={sendCode}>
              {busy ? "SENDING..." : "SEND CODE"}
            </button>
          </>
        )}

        {step === "code" && (
          <>
            <p className="login-hint">Code sent to {email}</p>
            <input
              inputMode="numeric"
              maxLength={6}
              placeholder="6-digit code"
              value={code}
              autoFocus
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              onKeyDown={(e) => e.key === "Enter" && code.length === 6 && checkCode()}
            />
            <button disabled={busy || code.length !== 6} onClick={checkCode}>
              {busy ? "CHECKING..." : "VERIFY"}
            </button>
            <button className="link" disabled={busy || cooldown > 0} onClick={sendCode}>
              {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend code"}
            </button>
            <button className="link" onClick={() => { setStep("email"); setCode(""); setError(""); }}>
              Change email
            </button>
          </>
        )}

        {step === "details" && (
          <>
            <p className="login-hint">Welcome! Tell us a bit about you to finish signing up.</p>
            <input placeholder="Full name *" value={details.name} onChange={set("name")} autoFocus />
            <input placeholder="Phone" value={details.phone} onChange={set("phone")} />
            <input placeholder="Role (e.g. operator, student)" value={details.role} onChange={set("role")} />
            <button disabled={busy || details.name.trim().length < 2} onClick={finishSignup}>
              {busy ? "SAVING..." : "CREATE ACCOUNT"}
            </button>
          </>
        )}

        {error && <p className="login-error">{error}</p>}
      </div>
    </div>
  );
}