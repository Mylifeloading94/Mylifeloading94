"""Module 6 - RSI / %B divergence (bullish form; bearish = same code on mirrored series).
Regular bullish divergence: price prints a lower low than the reference swing low while the
oscillator prints a higher low."""


def bullish(price_now, price_ref, osc_now, osc_ref):
    if osc_now != osc_now or osc_ref != osc_ref: return False
    return price_now < price_ref and osc_now > osc_ref
