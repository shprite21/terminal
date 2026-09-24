#pragma once
namespace pricing {
struct Greeks { double delta, gamma, vega, theta, rho; };
double black_scholes_price(double, double, double, double, double, int);
Greeks black_scholes_greeks(double, double, double, double, double, int);
}
