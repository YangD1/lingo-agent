"""Every evaluator, by name. `python -m evals` and the replay tests run them all."""

from evals.critic import CriticEval
from evals.diagnosis import DiagnosisEval
from evals.grader import GraderEval
from evals.reading_critic import ReadingCriticEval
from evals.reflect import ReflectEval
from evals.route import RouteEval
from evals.runner import Evaluator
from evals.speaking_summary import SpeakingSummaryEval
from evals.writing_review import WritingReviewEval

EVALUATORS: dict[str, Evaluator] = {
    e.name: e
    for e in (
        CriticEval(),
        GraderEval(),
        DiagnosisEval(),
        SpeakingSummaryEval(),
        RouteEval(),
        ReflectEval(),
        WritingReviewEval(),
        ReadingCriticEval(),
    )
}
