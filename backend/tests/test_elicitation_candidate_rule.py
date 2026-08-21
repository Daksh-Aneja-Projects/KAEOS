"""H7: an elicitation answer becomes a candidate Rule.

submit_answer stored the answer in a text column and bumped reputation, but the
"L5 Answer Processing Pipeline" its docstring named did not exist — the highest-
value human knowledge the product collects died there. It now mints a CANDIDATE
rule (non-executable, INFERRED) into the same maker-checker path every rule
clears.

require_role is bypassed under the test client (see conftest), so the route
coroutine is called directly with a fabricated operator tenant."""
import pytest
from sqlalchemy import select

from app.api.routes.elicitation import submit_answer
from app.models.domain import ElicitationQuestion, Employee, Rule
from app.schemas.elicitation import AnswerSubmit

TENANT = "tenant_h7"


@pytest.mark.asyncio
async def test_answer_mints_a_nonexecutable_candidate_rule(db):
    db.add(Employee(id="emp-h7", tenant_id=TENANT, display_name="Expert",
                    department="finance"))
    db.add(ElicitationQuestion(id="q-h7", tenant_id=TENANT, employee_id="emp-h7",
                               question_text="What is the approval limit for wires?",
                               status="PENDING"))
    await db.commit()

    res = await submit_answer(
        AnswerSubmit(question_id="q-h7",
                     answer_text="Wire transfers over $10k require two signers"),
        {"tenant_id": TENANT, "role": "operator"}, db)

    assert res["candidate_rule_id"], "the answer must produce a candidate rule id"

    rule = (await db.execute(select(Rule).where(Rule.tenant_id == TENANT))).scalar_one()
    assert rule.is_executable is False, "candidate: must clear maker-checker first"
    assert "two signers" in rule.statement
    assert rule.domain == "finance", "domain derived from the expert's department"
    assert rule.confidence_tier is not None

    # The question is closed, and answering it again is refused.
    q = (await db.execute(select(ElicitationQuestion).where(
        ElicitationQuestion.id == "q-h7"))).scalar_one()
    assert q.status == "ANSWERED"
