"""Every evaluator, by name. `python -m evals` and the replay tests run them all."""

from evals.runner import Evaluator

EVALUATORS: dict[str, Evaluator] = {}
