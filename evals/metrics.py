import math


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile_value * len(ordered)) - 1)
    return float(ordered[index])


def estimated_cost(input_tokens: int, output_tokens: int,
                   input_per_million: float, output_per_million: float) -> float:
    return round((max(0, input_tokens) * input_per_million +
                  max(0, output_tokens) * output_per_million) / 1_000_000, 8)
