"""
valentinos/games/ntv/test_ntv_logic.py
----------------------------------------
Tests for the NTV data layer: vehicles, rounds, scoring, arena gen.
No pygame. Run with:  python test_ntv_logic.py
"""

import sys
import os
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from valentinos.games.ntv.vehicles import (
    V1, V2A, V2B, V3A, V3B,
    INTRO_ORDER, ALL_VEHICLES, COMBINABLE,
    make_compound, compound_label, component_keys,
    VehicleDef,
)
from valentinos.games.ntv.rounds import (
    Round, Choice, SessionScore,
    generate_round, _complexity_for_round, _build_choices,
)
from valentinos.games.ntv.arena_gen import generate_arena

# ── Test infrastructure ────────────────────────────────────────────────────────

_passed = _failed = 0

def check(label, condition, detail=""):
    global _passed, _failed
    if condition:
        print(f"  ✓  {label}")
        _passed += 1
    else:
        print(f"  ✗  {label}")
        if detail:
            print(f"     {detail}")
        _failed += 1

def section(title):
    print(f"\n[{title}]")

def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


# ── Vehicle definitions ────────────────────────────────────────────────────────

def test_vehicles():
    section("Vehicle definitions")
    check("5 vehicles defined",          len(INTRO_ORDER) == 5)
    check("V1 full_name correct",
          V1.full_name == "Vehicle 1, or Obstacle Avoidance")
    check("V2A full_name has all names",
          "Cowardice" in V2A.full_name and "Fear" in V2A.full_name)
    check("V2A short_name is Cowardice", V2A.short_name == "Cowardice")
    check("V3A has neuron biases",       V3A.config.neuron_biases.get("N1") == 1.0)
    check("V1 uses IR sensors",
          any(c.source in ("RL","RR") for c in V1.config.connections))
    check("V2A uses LDR sensors",
          any(c.source in ("PL","PR") for c in V2A.config.connections))
    check("ALL_VEHICLES keyed correctly",
          ALL_VEHICLES["v2b"].label == "Vehicle 2b")


def test_compound():
    section("Compound vehicle building")
    comp = make_compound([V2A, V3A])
    # Should have connections from both
    sources = {c.source for c in comp.connections}
    check("Compound has PL from V2A",    "PL" in sources)
    check("Compound has N1 from V3A",    "N1" in
          {c.source for c in comp.connections})
    check("Compound biases merged",      comp.neuron_biases.get("N1") == 1.0)
    check("No duplicate connections",
          len(comp.connections) == len(set(
              (c.source, c.dest, c.color) for c in comp.connections)))

    # Three-way
    comp3 = make_compound([V2A, V2B, V3A])
    check("Triple compound has connections from all three",
          len(comp3.connections) > len(make_compound([V2A, V2B]).connections))

    check("compound_label format correct",
          compound_label([V2A, V3A]) == "Cowardice + Love")
    check("component_keys returns frozenset",
          isinstance(component_keys([V2A, V3A]), frozenset))


# ── Round complexity ───────────────────────────────────────────────────────────

def test_complexity():
    section("Round complexity schedule")
    cases = [
        (1,  1, 3), (5,  1, 3),
        (6,  1, 5), (10, 1, 5),
        (11, 2, 5), (25, 2, 5),
        (26, 3, 5), (40, 3, 5),
    ]
    for rn, exp_n, exp_c in cases:
        n, c = _complexity_for_round(rn)
        check(f"Round {rn}: n_behaviors={exp_n}, n_choices={exp_c}",
              n == exp_n and c == exp_c,
              f"got n={n}, c={c}")


# ── Round generation ───────────────────────────────────────────────────────────

def test_round_generation():
    section("Round generation")
    rng = random.Random(42)

    r1 = generate_round(1, rng)
    check("Round 1: 1 behavior",         r1.n_behaviors == 1)
    check("Round 1: 3 choices",          len(r1.choices) == 3)
    check("Round 1: correct in choices",
          any(c.keys == r1.correct_keys for c in r1.choices))

    r6 = generate_round(6, rng)
    check("Round 6: 5 choices",          len(r6.choices) == 5)

    r11 = generate_round(11, rng)
    check("Round 11: 2 behaviors",       r11.n_behaviors == 2)
    check("Round 11: 5 choices",         len(r11.choices) == 5)
    check("Round 11: correct in choices",
          any(c.keys == r11.correct_keys for c in r11.choices))
    # All choices should be pairs
    check("Round 11: all choices are pairs",
          all(len(c.components) == 2 for c in r11.choices))

    r26 = generate_round(26, rng)
    check("Round 26: 3 behaviors",       r26.n_behaviors == 3)


# ── Scoring — single behavior ──────────────────────────────────────────────────

def test_scoring_single():
    section("Scoring — single behavior round")
    rng = random.Random(99)
    r   = generate_round(1, rng)
    correct_choice = next(c for c in r.choices if c.keys == r.correct_keys)
    wrong_choice   = next(c for c in r.choices if c.keys != r.correct_keys)

    # Wrong guess first
    res1 = r.evaluate_guess(wrong_choice)
    check("Wrong guess: no correct delta",  near(res1["correct_delta"], 0.0))
    check("Wrong guess: not round_over",    not res1["round_over"])
    check("Wrong guess: guesses_made=1",    res1["guesses_made"] == 1)

    # Correct guess second
    res2 = r.evaluate_guess(correct_choice)
    check("Correct guess: delta=1.0",       near(res2["correct_delta"], 1.0))
    check("Correct guess: all_found",       res2["all_found"])
    check("Correct guess: round_over",      res2["round_over"])
    check("Correct guess: no reveal",       not res2["reveal"])

    # Incorrect fraction = 0 (found it)
    check("Incorrect fraction = 0.0",       near(r.incorrect_fraction(), 0.0))


def test_scoring_three_wrong():
    section("Scoring — three wrong guesses triggers reveal")
    rng = random.Random(7)
    r   = generate_round(6, rng)   # 5 choices, 1 behavior
    wrong_choices = [c for c in r.choices if c.keys != r.correct_keys]

    for i in range(3):
        choice = wrong_choices[i % len(wrong_choices)]
        res = r.evaluate_guess(choice)

    check("Round over after 3 wrong",       r.round_over)
    check("Reveal flagged",                 res["reveal"])
    check("Incorrect fraction = 1.0",       near(r.incorrect_fraction(), 1.0))


# ── Scoring — multi-behavior ───────────────────────────────────────────────────

def test_scoring_multi():
    section("Scoring — multi-behavior round (2 behaviors)")
    rng = random.Random(13)
    r   = generate_round(11, rng)
    assert r.n_behaviors == 2

    # Build a choice that has exactly ONE correct component
    correct_keys = r.correct_keys
    one_right = None
    for c in r.choices:
        overlap = c.keys & correct_keys
        if len(overlap) == 1 and len(c.keys) == 2:
            one_right = c
            break

    if one_right is None:
        # Build one manually from correct components + wrong
        correct_comp = r.correct[0]
        wrong_comp   = next(v for v in COMBINABLE
                            if v.key not in correct_keys)
        one_right = Choice.from_components([correct_comp, wrong_comp])

    res = r.evaluate_guess(one_right)
    check("Partial guess: correct_delta = 0.5",
          near(res["correct_delta"], 0.5, tol=0.01))
    check("Partial guess: not all_found",   not res["all_found"])
    check("Partial guess: not round_over",  not res["round_over"])

    # Now guess the full correct answer
    correct_choice = next(c for c in r.choices if c.keys == correct_keys)
    res2 = r.evaluate_guess(correct_choice)
    # The remaining component should now be found
    check("Second guess finds remaining",   res2["all_found"])
    # correct_delta should be 0.5 (the missing half)
    check("Second guess delta = 0.5",
          near(res2["correct_delta"], 0.5, tol=0.01))

    check("Incorrect fraction = 0.0",       near(r.incorrect_fraction(), 0.0))


def test_no_double_credit():
    section("No double-credit for same component")
    rng = random.Random(17)
    r   = generate_round(11, rng)
    assert r.n_behaviors == 2

    correct_choice = next(c for c in r.choices if c.keys == r.correct_keys)

    res1 = r.evaluate_guess(correct_choice)
    total_after_1 = res1["correct_delta"]

    # Guess the same correct answer again
    res2 = r.evaluate_guess(correct_choice)
    check("Already-found components give 0 delta",
          near(res2["correct_delta"], 0.0))
    check("already_had populated",         len(res2["already_had"]) > 0)


# ── Session score ──────────────────────────────────────────────────────────────

def test_session_score():
    section("Session score accumulation")
    score = SessionScore()
    rng   = random.Random(55)

    # Round 1: get it right
    r1 = generate_round(1, rng)
    cc = next(c for c in r1.choices if c.keys == r1.correct_keys)
    res = r1.evaluate_guess(cc)
    score.apply_round(r1, extra_correct=res["correct_delta"])
    check("After correct round: correct=1.0",  near(score.correct, 1.0))
    check("After correct round: incorrect=0.0", near(score.incorrect, 0.0))
    check("Rounds count=1",                     score.rounds == 1)

    # Round 2: get it wrong three times
    r2 = generate_round(2, rng)
    wrong_choices = [c for c in r2.choices if c.keys != r2.correct_keys]
    for i in range(3):
        r2.evaluate_guess(wrong_choices[i % len(wrong_choices)])
    score.apply_round(r2)
    check("After failed round: incorrect=1.0",  near(score.incorrect, 1.0))
    check("Rounds count=2",                      score.rounds == 2)


# ── Arena generation ───────────────────────────────────────────────────────────

def test_arena_gen():
    section("Arena generation")
    rng = random.Random(88)

    a_light = generate_arena("light", rng)
    check("Light arena has light source",
          len(a_light["light_sources"]) == 1)
    check("Light arena has no internal walls",
          len(a_light["internal_walls"]) == 0)
    ls = a_light["light_sources"][0]
    check("Light not on centreline",     abs(ls["x"]) >= 0.10)

    a_obs = generate_arena("obstacle", rng)
    check("Obstacle arena has wall",
          len(a_obs["internal_walls"]) == 1)
    check("Obstacle arena has no lights",
          len(a_obs["light_sources"]) == 0)

    a_both = generate_arena("both", rng)
    check("Both arena has light and wall",
          len(a_both["light_sources"]) >= 1 and
          len(a_both["internal_walls"]) >= 1)

    # Robot start is at bottom centre
    rs = a_light["robot_start"]
    check("Robot starts at bottom centre",
          rs["x"] == 0.0 and rs["y"] < 0.0)
    check("Robot heading is upward (90°)", rs["heading_deg"] == 90.0)


# ── Feedback strings ───────────────────────────────────────────────────────────

def test_feedback():
    section("Feedback string generation")
    rng = random.Random(33)
    r   = generate_round(1, rng)
    cc  = next(c for c in r.choices if c.keys == r.correct_keys)
    wc  = next(c for c in r.choices if c.keys != r.correct_keys)

    res_wrong = r.evaluate_guess(wc)
    fb_wrong  = r.feedback_for_guess(res_wrong)
    check("Wrong guess 1 says 'Try again'",   "Try again" in fb_wrong)

    res_wrong2 = r.evaluate_guess(wc)
    fb_wrong2  = r.feedback_for_guess(res_wrong2)
    check("Wrong guess 2 says 'One last'",    "last" in fb_wrong2.lower())

    res_correct = r.evaluate_guess(cc)
    fb_correct  = r.feedback_for_guess(res_correct)
    check("Correct guess says 'Well done'",   "Well done" in fb_correct)


def test_feedback_reveal():
    section("Feedback reveal after 3 wrong")
    rng = random.Random(77)
    r   = generate_round(6, rng)
    wcs = [c for c in r.choices if c.keys != r.correct_keys]
    last_res = None
    for i in range(3):
        last_res = r.evaluate_guess(wcs[i % len(wcs)])
    fb = r.feedback_for_guess(last_res)
    check("Reveal feedback contains answer",  "answer" in fb.lower() or
          any(v.short_name in fb for v in r.correct))


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_vehicles()
    test_compound()
    test_complexity()
    test_round_generation()
    test_scoring_single()
    test_scoring_three_wrong()
    test_scoring_multi()
    test_no_double_credit()
    test_session_score()
    test_arena_gen()
    test_feedback()
    test_feedback_reveal()

    print(f"\n{'='*50}")
    print(f"  Results: {_passed} passed,  {_failed} failed")
    print(f"{'='*50}\n")

    sys.exit(0 if _failed == 0 else 1)
