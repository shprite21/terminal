// Q benchmark: exact shared inputs, timed pricing + Greeks, I/O excluded.
#include <array>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <vector>
#include "q_pricing.hpp"
int main() {
    int count=0, repeats=0;
    if (!(std::cin >> count >> repeats) || count < 1 || count > 20000 || repeats < 1 || repeats > 5) return 2;
    std::vector<std::array<double,6>> inputs(count), outputs(count);
    for (auto& row:inputs) {
        for (auto& x:row) if (!(std::cin >> x) || !std::isfinite(x)) return 2;
        if (row[0]<=0 || row[1]<=0 || row[2]<0 || row[4]<0 || (row[5]!=1 && row[5]!=-1)) return 2;
    }
    std::vector<double> seconds;
    for (int rep=0;rep<repeats;rep++) {
        const auto start=std::chrono::steady_clock::now();
        for (int i=0;i<count;i++) {
            const auto& x=inputs[i];
            const double price=pricing::black_scholes_price(x[0],x[1],x[2],x[3],x[4],int(x[5]));
            const auto g=pricing::black_scholes_greeks(x[0],x[1],x[2],x[3],x[4],int(x[5]));
            outputs[i]={price,g.delta,g.gamma,g.vega,g.theta,g.rho};
        }
        seconds.push_back(std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count());
    }
    std::cout << std::setprecision(17) << "{\"seconds\":[";
    for (int r=0;r<repeats;r++) { if(r) std::cout<<","; std::cout<<seconds[r]; }
    std::cout<<"],\"outputs\":[";
    for (int i=0;i<count;i++) {
        if(i) std::cout<<",";
        std::cout<<"[";
        for (int j=0;j<6;j++) {
            if(j) std::cout<<",";
            if(std::isfinite(outputs[i][j])) std::cout<<outputs[i][j]; else std::cout<<"null";
        }
        std::cout<<"]";
    }
    std::cout<<"]}";
}
