from datetime import datetime, timezone
from .models import Hypothesis

TEMPLATES = {
    "Trend continuation": ("Recent price strength predicts continued relative strength.", "momentum", "Compare different subperiods and a fixed buy-and-hold price baseline; increase costs; inspect dependence on the largest winners."),
    "Short-horizon mean reversion": ("Recent price weakness predicts a short-horizon reversal.", "mean_reversion", "Delay entries, raise spreads, and test liquidity restrictions; compare reversal with market exposure."),
    "Cross-sectional relative strength": ("Relatively stronger eligible stocks outperform weaker stocks.", "relative_strength", "Test contemporaneous eligibility, concentration, and alternative sourced universes; examine top-minus-bottom returns."),
    "Volume-conditioned price behavior": ("Price strength with unusual volume persists longer.", "volume_momentum", "Compare the same price rule without the volume condition; inspect low-liquidity dependence."),
}


def template(name, author="Local researcher"):
    explanation, feature, tests = TEMPLATES[name]
    return Hypothesis(name=name, family=name.lower().replace(" ", "_"), author=author, created_at=datetime.now(timezone.utc),
                      explanation=explanation, signal_definition=feature, planned_experiments=tests).model_dump(mode="json")


def guidance(hypothesis):
    h = Hypothesis.model_validate(hypothesis)
    return {"claim_type": "user assumption; not a computed finding", "missing": h.missing(),
            "questions": ["Specify " + field.replace("_", " ") + " before testing." for field in h.missing()],
            "falsification_checks": ["Specify rejection thresholds before viewing results.", "Compare a simple fixed benchmark on identical dates.",
                                      "Test whether costs, concentration, or current-universe selection explain the result.",
                                      "Bound and register every tested variant, including failed trials."],
            "event_template": "Unavailable until properly timestamped event data and an event-feature adapter are implemented."}
