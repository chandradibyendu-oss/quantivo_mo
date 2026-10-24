export type ApiError = {
  error: {
    code: string;
    message: string;
  };
};

export type TokenOut = {
  access_token: string;
  refresh_token: string;
  expires_in_seconds: number;
  user_id: string;
};

export type OtpRequestOut = {
  challenge_id: string;
  expires_in_seconds: number;
  delivery: "dev_mock";
  dev_otp: string | null;
};

export type ScannerOut = {
  id: string;
  provider_name: string;
  monogram: string;
  name: string;
  description: string;
  price_inr: string | null;
  billing_frequency: string | null;
  entitlement_status: "none" | "active";
};

export type TargetOut = {
  label: string;
  price: string;
  risk_reward: string | null;
};

export type SignalCard = {
  id: string;
  symbol: string;
  exchange: string;
  side: string;
  product_hint: "MIS" | "CNC";
  status: string;
  warning: string | null;
  executable: boolean;
  guide:
    | "waiting"
    | "window_over"
    | "checking"
    | "caution"
    | "not_valid"
    | "entry"
    | "t1_trail"
    | "t2_trail"
    | "trail"
    | "final"
    | "stop"
    | "stale"
    | "expired"
    | "no_symbol";
  guide_label: string;
  guide_hint: string;
  published_at: string;
  provider_name: string;
  scanner_name: string;
  segment: string;
  channel_name: string;
  horizon_raw: string;
  lot_size: number;
  provider_values: {
    source: "provider";
    trigger_price: string;
    stop_loss: string;
    targets: TargetOut[];
    note: string | null;
  };
  quantivo_values: {
    source: "quantivo";
    suggested_quantity: number | null;
    per_share_risk: string | null;
    formula: string;
    funds_check: string;
    unavailable_reason: string | null;
    max_risk_inr: string;
  };
  suggested_quantity: number | null;
  last_price?: string | null;
  change_percent?: string | null;
  quote_label?: "LTP" | "Last LTP";
  quote_state?: "ready" | "missing" | "unconfigured" | "unavailable";
};

export type ChartCandle = {
  time: string;
  open: string;
  high: string;
  low: string;
  close: string;
};

export type SignalChart = {
  symbol: string;
  side: string;
  interval: "1m" | "5m";
  session_date: string;
  quote_label: "LTP" | "Last LTP";
  last_price: string | null;
  change_percent?: string | null;
  quote_state: "ready" | "checking" | "missing" | "unconfigured" | "unavailable";
  trigger_price: string;
  stop_loss: string;
  targets: { label: string; price: string }[];
  candles: ChartCandle[];
};

export type SignalDetail = SignalCard & {
  broker: {
    status: string;
    order_placement: "disabled";
    message: string;
  };
};

export type MeOut = {
  id: string;
  phone_e164: string;
  display_name: string | null;
  status: string;
  roles: string[];
};

export type FeedKind = "none" | "telegram" | "http_api";

export type FeedOut = {
  channel_id: string;
  scanner_id: string;
  scanner_name: string;
  channel_code: string;
  channel_name: string;
  segment: string;
  kind: FeedKind;
  status: "active" | "inactive";
  options: Record<string, string | number>;
  stored_calls: number;
  reader: {
    state: "sample" | "login_not_configured" | "login_present" | "saved";
    detail: string;
  };
};

export type TelegramLoginOut = {
  status: "present" | "missing";
  detail: string;
};

export type FyersConfigOut = {
  configured: boolean;
  app_saved: boolean;
  connected: boolean;
  refresh_until: string | null;
  detail: string;
};

export type FyersConnectOut = {
  url: string;
};

export type CallClocksOut = {
  intraday_btst_minutes: number;
  short_term_days: number;
  long_term_days: number;
};

export type ChannelMatch = {
  channel_id: string;
  title: string;
};

export type ChannelLookupOut = {
  matches: ChannelMatch[];
};

export type TraderChannel = {
  id: string;
  scanner_id: string;
  name: string;
  segment: string;
  registered: boolean;
};

export type SignalListOut = {
  entitled: boolean;
  scanner_name: string | null;
  provider_name: string | null;
  feed_mode: "mock" | "telegram" | "telegram_pending";
  hidden_non_actionable: number;
  omitted_channels?: string[];
  registration_required?: boolean;
  selected_channel_name?: string | null;
  quote_feed?: "fyers" | "unconfigured" | "unavailable";
  signals: SignalCard[];
};
