from app.modules.feeds.equity_directory import EquityDirectory, EquityRecord, parse_fyers_nse_cm
from app.modules.feeds.normalize import match_posted_name

_ROWS = [
    EquityRecord("HDFCBANK", "HDFC Bank Limited", "EQ"),
    EquityRecord("SMLMAH", "SML Mahindra Limited", "EQ"),
    EquityRecord("TATASTEEL", "Tata Steel Limited", "EQ"),
    EquityRecord("TATAPOWER", "Tata Power Company Limited", "EQ"),
    EquityRecord("TEGA", "Tega Industries Limited", "EQ"),
    EquityRecord("AEGISLOG", "Aegis Logistics Limited", "EQ"),
    EquityRecord("LAXMIORGO", "Laxmi Organic Industries Limited", "EQ"),
]


def _directory() -> EquityDirectory:
    return EquityDirectory(_ROWS)


def test_a_company_name_resolves_to_one_nse_symbol():
    symbol, status, note = match_posted_name("SML Mahindra", _directory())
    assert (symbol, status, note) == ("SMLMAH", "matched", None)
    symbol, status, note = match_posted_name("HDFC Bank", _directory())
    assert (symbol, status, note) == ("HDFCBANK", "matched", None)


def test_two_companies_stay_ambiguous_and_a_missing_name_stays_unmatched():
    symbol, status, note = match_posted_name("Tata", _directory())
    assert symbol == "TATA"
    assert status == "ambiguous"
    assert note == "The posted name matches more than one NSE symbol."
    symbol, status, note = match_posted_name("Not A Listed Name", _directory())
    assert status == "unmatched"
    assert symbol == "NOT A LISTED NAME"


def test_a_trailing_industry_word_uses_the_ticker_and_a_channel_spelling_uses_its_alias():
    symbol, status, _note = match_posted_name("TEGA IND", _directory())
    assert (symbol, status) == ("TEGA", "matched")
    symbol, status, note = match_posted_name("Aegies Logistics", None)
    assert (symbol, status, note) == ("AEGISLOG", "matched", None)


def test_a_former_ticker_resolves_to_the_current_listing():
    directory = EquityDirectory([EquityRecord("LTM", "LTM Limited", "EQ")])
    symbol, status, note = match_posted_name("LTIM", directory)
    assert (symbol, status, note) == ("LTM", "matched", None)
    missing = EquityDirectory([EquityRecord("HDFCBANK", "HDFC Bank Limited", "EQ")])
    _symbol, status, _note = match_posted_name("LTIM", missing)
    assert status == "unmatched"


def test_without_the_list_a_single_ticker_matches_and_a_company_name_does_not():
    symbol, status, _note = match_posted_name("RELIANCE", None)
    assert (symbol, status) == ("RELIANCE", "matched")
    _symbol, status, _note = match_posted_name("HDFC Bank", None)
    assert status == "unmatched"


def test_fyers_cash_row_becomes_a_symbol_and_company():
    text = "x,HDFC Bank Limited,a,b,c,d,e,f,g,NSE:HDFCBANK-EQ\n"
    records = parse_fyers_nse_cm(text)
    assert len(records) == 1
    assert records[0].symbol == "HDFCBANK"
    assert records[0].company_name == "HDFC Bank Limited"
