"""Module 4 - liquidity: confirmed swing pivots and sweeps of them.
A pivot at bar j is only known at bar j+R (when its right side has closed) -> no lookahead."""


def pivot_lows(l, L, R):
    """List of (confirm_index, pivot_index, price)."""
    out = []
    for j in range(L, len(l) - R):
        v = l[j]
        if all(v < l[k] for k in range(j - L, j)) and all(v <= l[k] for k in range(j + 1, j + R + 1)):
            out.append((j + R, j, v))
    return out


def pivot_highs(h, L, R):
    return [(ci, j, -p) for ci, j, p in pivot_lows([-x for x in h], L, R)]


class Pool:
    """Unswept liquidity levels below price (pivot lows). Feed bars in order with update(i, low)."""
    def __init__(self, piv, lookback):
        self.piv = piv; self.k = 0; self.active = []; self.lookback = lookback

    def update(self, i, low):
        """Add pivots confirmed by bar i-1 (so bar i can sweep them); return levels swept by bar i."""
        while self.k < len(self.piv) and self.piv[self.k][0] <= i - 1:
            self.active.append(self.piv[self.k][1:]); self.k += 1
        self.active = [p for p in self.active if p[0] >= i - self.lookback]
        swept = [p for p in self.active if low < p[1]]
        if swept: self.active = [p for p in self.active if low >= p[1]]
        return swept                                  # [(pivot_index, price), ...]

    def nearest_below(self, price):
        below = [p for _, p in self.active if p < price]
        return max(below) if below else None
