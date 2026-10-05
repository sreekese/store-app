import { lazy, Suspense, useCallback, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authorized } from "../auth/client";
import { Field, Feedback, QueryState, type Store } from "../profiles/shared";
import type { OfferFields } from "../offers/types";
const Scanner = lazy(() => import("./Scanner"));
interface Receipt {
  id: string;
  claim_id: string;
  title: string;
  store_name: string;
  redeemed_at: string;
  purchase_amount: string;
  discount_amount: string;
  payable_amount: string;
  currency: string;
}
interface Preview {
  claim_id: string;
  title: string;
  store_name: string;
  expires_at: string;
  offer: OfferFields;
  purchase_amount: string;
  discount_amount: string;
  payable_amount: string;
  confirmation_token: string;
  confirm_before: string;
}
export default function RedemptionDesk({ staff = false }: { staff?: boolean }) {
  const [store, setStore] = useState(""),
    [token, setToken] = useState(""),
    [purchase, setPurchase] = useState(""),
    [reward, setReward] = useState(""),
    [preview, setPreview] = useState<Preview | null>(null),
    [confirmed, setConfirmed] = useState(false),
    [scanning, setScanning] = useState(false),
    [offset, setOffset] = useState(0),
    key = useRef<string | null>(null),
    client = useQueryClient();
  const stores = useQuery({
    queryKey: [staff ? "staff-stores" : "merchant-stores"],
    queryFn: () =>
      authorized<Store[]>(`/${staff ? "staff" : "merchant"}/stores`),
    retry: false,
    refetchInterval: 30000,
  });
  const history = useQuery({
    queryKey: ["redemptions", store, offset],
    queryFn: () =>
      authorized<Receipt[]>(`/redemptions?store_id=${store}&offset=${offset}`),
    enabled: !!store,
    retry: false,
    refetchInterval: 30000,
  });
  const payload = () => ({
    store_id: store,
    claim_token: token.trim(),
    purchase_amount: purchase,
    reward_value: reward || null,
  });
  const validate = useMutation({
    mutationFn: () =>
      authorized<Preview>("/redemptions/validate", {
        method: "POST",
        body: JSON.stringify(payload()),
      }),
    onSuccess: (data) => {
      setPreview(data);
      setConfirmed(false);
    },
    onError: () => setPreview(null),
  });
  const redeem = useMutation({
    mutationFn: () => {
      key.current ||= crypto.randomUUID();
      return authorized<Receipt>("/redemptions", {
        method: "POST",
        headers: { "Idempotency-Key": key.current },
        body: JSON.stringify({
          ...payload(),
          confirmation_token: preview!.confirmation_token,
          terms_confirmed: true,
        }),
      });
    },
    onSuccess: () => {
      setPreview(null);
      setToken("");
      setPurchase("");
      setReward("");
      setConfirmed(false);
      key.current = null;
      void client.invalidateQueries({ queryKey: ["redemptions"] });
    },
  });
  function changed() {
    setPreview(null);
    setConfirmed(false);
    key.current = null;
    validate.reset();
    redeem.reset();
    setScanning(false);
  }
  const read = useCallback((value: string) => {
    setToken(value);
    setPreview(null);
    setConfirmed(false);
    key.current = null;
    setScanning(false);
  }, []);
  const busy = validate.isPending || redeem.isPending;
  return (
    <section className="account-panel">
      <p className="eyebrow">AT THE COUNTER</p>
      <h2>Redeem a coupon</h2>
      <p>
        Select your branch, scan or paste the shopper’s code, then validate
        before confirming. This records a coupon benefit; it does not process a
        payment.
      </p>
      <QueryState
        pending={stores.isPending}
        error={stores.error}
        retry={stores.refetch}
      />
      <form
        className="profile-form"
        onSubmit={(e) => {
          e.preventDefault();
          setScanning(false);
          setPreview(null);
          redeem.reset();
          validate.mutate();
        }}
      >
        <fieldset disabled={busy}>
          <label>
            Redemption branch
            <select
              required
              value={store}
              onChange={(e) => {
                changed();
                setStore(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">Choose a branch</option>
              {stores.data
                ?.filter((s) => s.status === "ACTIVE")
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} · {s.city}
                  </option>
                ))}
            </select>
          </label>
          <div className="form-actions">
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setPreview(null);
                setScanning(!scanning);
              }}
            >
              {scanning ? "Stop camera" : "Scan QR code"}
            </button>
          </div>
          {scanning && (
            <Suspense fallback={<p role="status">Preparing camera…</p>}>
              <Scanner onRead={read} />
            </Suspense>
          )}
          <Field
            label="Manual coupon code"
            required
            minLength={20}
            maxLength={100}
            autoComplete="off"
            spellCheck={false}
            value={token}
            onChange={(e) => {
              changed();
              setToken(e.target.value);
            }}
          />
          <Field
            label="Eligible original total (₹)"
            type="number"
            required
            min={0}
            step="0.01"
            max="9999999999.99"
            value={purchase}
            onChange={(e) => {
              changed();
              setPurchase(e.target.value);
            }}
          />
          <p>
            Enter the eligible items’ total before this discount, including any
            free item. Exclude items disallowed by the saved terms.
          </p>
          <Field
            label="Free-item regular value (₹, BOGO/free-item offers only)"
            type="number"
            min="0.01"
            step="0.01"
            max="9999999999.99"
            value={reward}
            onChange={(e) => {
              changed();
              setReward(e.target.value);
            }}
          />
          <button className="button" disabled={!store || busy}>
            {validate.isPending ? "Validating…" : "Validate coupon"}
          </button>
        </fieldset>
      </form>
      <Feedback error={validate.error || redeem.error} />
      {preview && (
        <div className="redemption-preview">
          <h3>{preview.title}</h3>
          <p>
            {preview.store_name} · expires{" "}
            {new Date(preview.expires_at).toLocaleString()}
          </p>
          <p className="offer-terms">{preview.offer.terms_conditions}</p>
          <dl className="offer-facts">
            <div>
              <dt>Recorded eligible purchase</dt>
              <dd>₹{preview.purchase_amount}</dd>
            </div>
            <div>
              <dt>Calculated benefit</dt>
              <dd>₹{preview.discount_amount}</dd>
            </div>
            <div>
              <dt>Eligible total after discount</dt>
              <dd>₹{preview.payable_amount}</dd>
            </div>
          </dl>
          <p>
            Confirm before {new Date(preview.confirm_before).toLocaleString()}.
            The server checks access and eligibility again when you confirm.
          </p>
          <label className="check-label">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={busy}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            I checked eligible items, exclusions, and all saved offer conditions
            with the shopper.
          </label>
          <button
            className="button"
            disabled={
              !confirmed ||
              busy ||
              !stores.data?.some((s) => s.id === store && s.status === "ACTIVE")
            }
            onClick={() => redeem.mutate()}
          >
            {redeem.isPending ? "Confirming…" : "Confirm redemption"}
          </button>
        </div>
      )}
      {redeem.data && (
        <div className="notice" role="status">
          <h3>Coupon redeemed</h3>
          <p>
            {redeem.data.title} · {redeem.data.store_name}
          </p>
          <p>
            Benefit ₹{redeem.data.discount_amount} · eligible total after
            discount ₹{redeem.data.payable_amount}
          </p>
          <p>
            Receipt {redeem.data.id} ·{" "}
            {new Date(redeem.data.redeemed_at).toLocaleString()}
          </p>
        </div>
      )}
      <h3>Redemption history</h3>
      <p>
        {staff
          ? "Your redemptions at your currently assigned branch."
          : "All redemptions at the selected owned branch."}{" "}
        Purchase values are staff-entered, not verified revenue.
      </p>
      {!store ? (
        <p>Select a branch to view its history.</p>
      ) : (
        <>
          <QueryState
            pending={history.isPending}
            error={history.error}
            retry={history.refetch}
          />
          {history.data && !history.isError && (
            <>
              {history.data.length === 0 && <p>No redemptions here yet.</p>}
              {history.data.map((r) => (
                <article className="branch-card" key={r.id}>
                  <h4>{r.title}</h4>
                  <p>
                    {new Date(r.redeemed_at).toLocaleString()} · {r.store_name}
                  </p>
                  <p>
                    Recorded purchase ₹{r.purchase_amount} · benefit ₹
                    {r.discount_amount}
                  </p>
                  <small>Receipt: {r.id}</small>
                </article>
              ))}
              <div className="form-actions">
                <button
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - 25))}
                >
                  Previous redemptions
                </button>
                <button
                  disabled={history.data.length < 25 || offset >= 10000}
                  onClick={() => setOffset(offset + 25)}
                >
                  More redemptions
                </button>
                <button onClick={() => void history.refetch()}>
                  Refresh history
                </button>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
