from datetime import datetime, timedelta, timezone

from portfolio.execution import MarketSession, MarketSessionStatus, PaperQuote


class SessionProvider:
    def session(self, *, as_of, calendar_name):
        return MarketSession(
            as_of=as_of,
            status=MarketSessionStatus.OPEN,
            calendar_name=calendar_name,
            opened_at=as_of - timedelta(hours=1),
            closes_at=as_of + timedelta(hours=5),
        )


class ClosedSessionProvider:
    def session(self, *, as_of, calendar_name):
        return MarketSession(as_of=as_of, status=MarketSessionStatus.CLOSED, calendar_name=calendar_name)


class QuoteProvider:
    def quotes(self, *, symbols, as_of):
        values = {
            "AAA": PaperQuote("AAA", as_of, 99.0, 101.0, 100.0, 10_000_000.0, source_identifier="test:AAA"),
            "BBB": PaperQuote("BBB", as_of, 49.0, 51.0, 50.0, 10_000_000.0, source_identifier="test:BBB"),
        }
        return {symbol: values[symbol] for symbol in symbols}


def session_provider():
    return SessionProvider()


def closed_session_provider():
    return ClosedSessionProvider()


def quote_provider():
    return QuoteProvider()
