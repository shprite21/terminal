#include <algorithm>
#include <cmath>
#include <limits>
#include "q_pricing.hpp"

namespace pricing {
namespace {
constexpr double kInvSqrt2 = 0.70710678118654752440;

double normal_cdf(double x) {
    return 0.5 * std::erfc(-x * kInvSqrt2);
}

double intrinsic_value(double spot, double strike, int option_type) {
    if (option_type >= 0) {
        return std::max(spot - strike, 0.0);
    }
    return std::max(strike - spot, 0.0);
}
}  // namespace

double black_scholes_price(
    double spot,
    double strike,
    double time_to_maturity,
    double risk_free_rate,
    double volatility,
    int option_type
) {
    if (!std::isfinite(spot) || !std::isfinite(strike) || !std::isfinite(time_to_maturity)
        || !std::isfinite(risk_free_rate) || !std::isfinite(volatility)
        || spot <= 0.0 || strike <= 0.0 || time_to_maturity < 0.0 || volatility < 0.0
        || (option_type != 1 && option_type != -1)) {
        return std::numeric_limits<double>::quiet_NaN();
    }

    if (time_to_maturity == 0.0) {
        return intrinsic_value(spot, strike, option_type);
    }

    const double discount_factor = std::exp(-risk_free_rate * time_to_maturity);
    if (volatility == 0.0) {
        return std::max(option_type * (spot - strike * discount_factor), 0.0);
    }

    const double sqrt_t = std::sqrt(time_to_maturity);
    const double variance = volatility * volatility;
    const double d1 = (
        std::log(spot / strike)
        + (risk_free_rate + 0.5 * variance) * time_to_maturity
    ) / (volatility * sqrt_t);
    const double d2 = d1 - volatility * sqrt_t;

    if (option_type >= 0) {
        return std::max(0.0, spot * normal_cdf(d1) - strike * discount_factor * normal_cdf(d2));
    }
    return std::max(0.0, strike * discount_factor * normal_cdf(-d2) - spot * normal_cdf(-d1));
}
}  // namespace pricing
