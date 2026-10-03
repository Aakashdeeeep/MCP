"""The red-team scenarios from evals/redteam.py, as tests: any breach fails the build."""
import pytest

from evals import redteam

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("scenario", redteam.SCENARIOS, ids=lambda s: s.name)
async def test_no_breach(scenario):
    result = await redteam.run_scenario(scenario)
    assert result["breaches"] == []
    assert result["money_moved"] == 0
