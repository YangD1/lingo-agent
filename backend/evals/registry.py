"""Every evaluator, by name. `python -m evals` and the replay tests run them all."""

from evals.critic import CriticEval
from evals.diagnosis import DiagnosisEval
from evals.grader import GraderEval
from evals.runner import Evaluator

EVALUATORS: dict[str, Evaluator] = {
    e.name: e for e in (CriticEval(), GraderEval(), DiagnosisEval())
}
