"""Tests for bucktrader.comminfo module."""

from datetime import datetime

import pytest

from bucktrader.comminfo import CommInfoBase, CommType


class TestCommInfoDefaults:
    def test_stock_defaults(self):
        ci = CommInfoBase(stocklike=True)
        assert ci.stocklike is True
        assert ci.commtype == CommType.COMM_PERC
        assert ci.commission == 0.0
        assert ci.mult == 1.0
        assert ci.margin is None
        assert ci.leverage == 1.0

    def test_futures_defaults(self):
        ci = CommInfoBase(margin=1000.0)
        assert ci.stocklike is False
        assert ci.commtype == CommType.COMM_FIXED
        assert ci.margin == 1000.0

    def test_margin_overrides_stocklike(self):
        """Setting margin forces stocklike=False regardless of argument."""
        ci = CommInfoBase(stocklike=True, margin=500.0)
        assert ci.stocklike is False

    def test_explicit_commtype(self):
        ci = CommInfoBase(commtype=CommType.COMM_FIXED, stocklike=True)
        assert ci.commtype == CommType.COMM_FIXED


class TestGetSize:
    def test_stock_getsize(self):
        ci = CommInfoBase(stocklike=True)
        assert ci.getsize(50.0, 1000.0) == 20
        assert ci.getsize(50.0, 99.0) == 1
        assert ci.getsize(50.0, 49.0) == 0

    def test_stock_getsize_with_leverage(self):
        ci = CommInfoBase(stocklike=True, leverage=2.0)
        # With 2x leverage, $1000 buys $2000 worth at $50/share = 40 shares.
        assert ci.getsize(50.0, 1000.0) == 40

    def test_futures_getsize(self):
        ci = CommInfoBase(margin=500.0)
        assert ci.getsize(100.0, 2500.0) == 5
        assert ci.getsize(100.0, 499.0) == 0

    def test_getsize_zero_price(self):
        ci = CommInfoBase(stocklike=True)
        assert ci.getsize(0.0, 1000.0) == 0

    def test_automargin_getsize(self):
        ci = CommInfoBase(automargin=True, mult=10.0)
        # margin = price * mult = 50 * 10 = 500 per contract.
        assert ci.getsize(50.0, 1500.0) == 3


class TestGetOperationCost:
    def test_stock_cost(self):
        ci = CommInfoBase(stocklike=True)
        assert ci.getoperationcost(100, 50.0) == pytest.approx(5000.0)

    def test_stock_cost_with_leverage(self):
        ci = CommInfoBase(stocklike=True, leverage=2.0)
        assert ci.getoperationcost(100, 50.0) == pytest.approx(2500.0)

    def test_futures_cost(self):
        ci = CommInfoBase(margin=500.0)
        assert ci.getoperationcost(10, 100.0) == pytest.approx(5000.0)

    def test_sell_cost_uses_abs(self):
        ci = CommInfoBase(stocklike=True)
        assert ci.getoperationcost(-100, 50.0) == pytest.approx(5000.0)


class TestGetValueSize:
    def test_stock_value(self):
        ci = CommInfoBase(stocklike=True, mult=1.0)
        assert ci.getvaluesize(100, 50.0) == pytest.approx(5000.0)

    def test_futures_value_with_multiplier(self):
        ci = CommInfoBase(mult=10.0, margin=500.0)
        # value = 100 * 50 * 10 = 50000.
        assert ci.getvaluesize(100, 50.0) == pytest.approx(50000.0)


class TestGetCommission:
    def test_perc_commission_not_percabs(self):
        """Default percentage commission is divided by 100."""
        ci = CommInfoBase(commission=0.1, stocklike=True)
        # Rate = 0.1/100 = 0.001, on 100 shares at $50: 0.001 * 100 * 50 * 1 = 5.0.
        assert ci.getcommission(100, 50.0) == pytest.approx(5.0)

    def test_perc_commission_percabs(self):
        """With percabs, commission is used directly as a fraction."""
        ci = CommInfoBase(commission=0.001, stocklike=True, percabs=True)
        # 0.001 * 100 * 50 * 1 = 5.0.
        assert ci.getcommission(100, 50.0) == pytest.approx(5.0)

    def test_fixed_commission(self):
        ci = CommInfoBase(
            commission=2.0, commtype=CommType.COMM_FIXED, stocklike=True
        )
        # 2.0 * 100 = 200.
        assert ci.getcommission(100, 50.0) == pytest.approx(200.0)

    def test_fixed_commission_per_contract(self):
        ci = CommInfoBase(
            commission=1.5, commtype=CommType.COMM_FIXED, margin=1000.0
        )
        assert ci.getcommission(10, 100.0) == pytest.approx(15.0)

    def test_negative_size_uses_abs(self):
        ci = CommInfoBase(commission=0.001, stocklike=True, percabs=True)
        assert ci.getcommission(-100, 50.0) == pytest.approx(5.0)


class TestProfitAndLoss:
    def test_long_profit(self):
        ci = CommInfoBase(mult=1.0)
        assert ci.profitandloss(100, 50.0, 55.0) == pytest.approx(500.0)

    def test_long_loss(self):
        ci = CommInfoBase(mult=1.0)
        assert ci.profitandloss(100, 50.0, 45.0) == pytest.approx(-500.0)

    def test_short_profit(self):
        ci = CommInfoBase(mult=1.0)
        assert ci.profitandloss(-100, 50.0, 45.0) == pytest.approx(500.0)

    def test_with_multiplier(self):
        ci = CommInfoBase(mult=10.0)
        assert ci.profitandloss(100, 50.0, 55.0) == pytest.approx(5000.0)


class TestCashAdjust:
    def test_stock_no_adjustment(self):
        ci = CommInfoBase(stocklike=True)
        assert ci.cashadjust(100, 50.0, 55.0) == 0.0

    def test_futures_mark_to_market(self):
        ci = CommInfoBase(margin=1000.0, mult=10.0)
        # 100 * (55 - 50) * 10 = 5000.
        assert ci.cashadjust(100, 50.0, 55.0) == pytest.approx(5000.0)

    def test_futures_loss(self):
        ci = CommInfoBase(margin=1000.0, mult=10.0)
        assert ci.cashadjust(100, 50.0, 45.0) == pytest.approx(-5000.0)


class TestCreditInterest:
    def test_no_interest(self):
        ci = CommInfoBase(interest=0.0)

        class FakePos:
            size = -100
            price = 50.0

        assert ci.get_credit_interest(None, FakePos()) == 0.0

    def test_short_interest(self):
        ci = CommInfoBase(interest=0.05, mult=1.0)  # 5% annual.

        class FakePos:
            size = -100
            price = 50.0

        daily = ci.get_credit_interest(None, FakePos())
        # Value = 100 * 50 = 5000. Daily = 5000 * 0.05 / 365.
        assert daily == pytest.approx(5000.0 * 0.05 / 365.0)

    def test_long_no_interest_by_default(self):
        ci = CommInfoBase(interest=0.05)

        class FakePos:
            size = 100
            price = 50.0

        assert ci.get_credit_interest(None, FakePos()) == 0.0

    def test_long_interest_when_enabled(self):
        ci = CommInfoBase(interest=0.05, interest_long=True)

        class FakePos:
            size = 100
            price = 50.0

        daily = ci.get_credit_interest(None, FakePos())
        assert daily > 0

    def test_flat_position_no_interest(self):
        ci = CommInfoBase(interest=0.05)

        class FakePos:
            size = 0
            price = 50.0

        assert ci.get_credit_interest(None, FakePos()) == 0.0

    def test_repr(self):
        ci = CommInfoBase(stocklike=True, commission=0.001)
        r = repr(ci)
        assert "stock" in r
        assert "0.001" in r
