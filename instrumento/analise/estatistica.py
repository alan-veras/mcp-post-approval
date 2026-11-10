"""A estatística da rodada 2: só o intervalo de Wilson de 95%. Sem testes de significância."""


Z95 = 1.959963984540054  # quantil 0,975 da normal padrão


def wilson(k, n, z=Z95):
    """Intervalo de Wilson de 95% para k sucessos em n: (inferior, superior)."""
    if n == 0:
        return (0.0, 1.0)
    p, z2 = k / n, z * z
    centro = (p + z2 / (2 * n)) / (1 + z2 / n)
    meia = z * ((p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5) / (1 + z2 / n)
    return (max(0.0, centro - meia), min(1.0, centro + meia))
