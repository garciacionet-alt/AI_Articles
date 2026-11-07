"""Tests for the roles: who talks, and who judges.

THE FEATURE
------------
Two roles, two models, and a catalogue that says which models can SEE
an image. The guide is `GET /v1/roles`; the choice is `POST /v1/roles`.

A critic that can see the image judges the PICTURE. One that cannot
judges only the prompt - and the first live run of the Agency burned
three generations chasing a defect the prompt judge invented, because
it could not look at the image it was judging.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from fake_device import FakeDevice
from tis.critic import Critic
from tis.models import RequirementVector
from tis.registry import Registry
from tis.roles import RoleError, Roles

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROLES_PATH = PROJECT_ROOT / "registry" / "roles.json"
REGISTRY_PATH = PROJECT_ROOT / "registry" / "image-models.json"

JUDGE = "Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo"
VISION_JUDGE = "Qwen/Qwen3.6-35B-A3B"


@pytest.fixture(scope="module")
def roles() -> Roles:
    return Roles.load(ROLES_PATH)


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY_PATH)


# -- the catalogue --------------------------------------------------------


def test_the_roles_catalogue_loads(roles: Roles):
    assert len(roles) > 0


def test_the_catalogue_knows_which_models_can_see(roles: Roles):
    """The flag the whole feature turns on."""
    vision = roles.vision_models()
    assert vision, "no model in the catalogue can see an image"
    assert all(m.vision for m in vision)
    assert all(not m.vision for m in roles.all() if m not in vision)


def test_the_vision_models_are_sorted_cheapest_first(roles: Roles):
    """The cheapest vision model that fits the pool is the one that runs."""
    vision = roles.vision_models()
    assert [m.npu_usage for m in vision] == sorted(m.npu_usage for m in vision)


def test_a_vision_model_is_marked_as_downloaded_or_running(roles: Roles):
    """A listed model is not a model on the disk."""
    for model in roles.vision_models():
        assert model.status in ("downloaded", "running", "not_downloaded")
        if model.status in ("downloaded", "running"):
            assert model.downloaded is True
        else:
            assert model.downloaded is False


def test_an_unknown_model_is_refused(roles: Roles):
    with pytest.raises(RoleError):
        roles.require("nobody/imagines-this-model")


def test_the_notes_say_who_measured_them(roles: Roles):
    """A model with no note has not been characterised, and says so."""
    curated = [m for m in roles.all() if m.notes]
    assert curated, "no model in the catalogue carries a note"
    for model in curated:
        assert model.provenance in ("m", "d")


# -- the critic -----------------------------------------------------------


def _device(registry: Registry, reply: str, *, resident=None) -> FakeDevice:
    return FakeDevice(
        registry,
        resident=resident if resident is not None else [JUDGE, VISION_JUDGE],
        replies={JUDGE: reply, VISION_JUDGE: reply},
    )


def test_a_blind_critic_judges_the_prompt(registry: Registry):
    device = _device(registry, "VERDICT: pass")
    critic = Critic(device, JUDGE, vision=False)
    critic.judge(b"\x89PNG", RequirementVector(), "A friendly robot.")

    assert ("chat", JUDGE) in device.calls
    assert not any(call[0] == "vision" for call in device.calls)
    prompt = device.prompts[-1]
    assert "cannot see the image" in prompt


def test_a_vision_critic_judges_the_picture(registry: Registry):
    """The image goes with the question."""
    device = _device(registry, "VERDICT: pass")
    critic = Critic(device, VISION_JUDGE, vision=True)
    critic.judge(b"\x89PNG", RequirementVector(), "A friendly robot.")

    assert ("vision", VISION_JUDGE) in device.calls
    assert not any(call[0] == "chat" for call in device.calls)


def test_a_vision_critic_is_not_told_it_cannot_see(registry: Registry):
    """Telling it so would make it reason about the prompt anyway."""
    device = _device(registry, "VERDICT: pass")
    Critic(device, VISION_JUDGE, vision=True).judge(
        b"\x89PNG", RequirementVector(), "A friendly robot.")

    prompt = device.prompts[-1]
    assert "CAN see the image" in prompt
    assert "cannot see the image" not in prompt


def test_a_vision_critic_is_told_to_judge_what_it_sees(registry: Registry):
    device = _device(registry, "VERDICT: pass")
    Critic(device, VISION_JUDGE, vision=True).judge(
        b"\x89PNG", RequirementVector(), "A friendly robot.")

    prompt = device.prompts[-1]
    assert "Judge what you see" in prompt
    assert "not the prompt against the" in prompt


def test_the_dimension_rule_holds_for_a_vision_critic_too(registry: Registry):
    """A change is an instruction whether or not the judge can see."""
    device = _device(registry, "VERDICT: pass")
    Critic(device, VISION_JUDGE, vision=True).judge(
        b"\x89PNG", RequirementVector(), "A friendly robot.")

    assert "Never ask for the image SIZE or RESOLUTION" in device.prompts[-1]


# -- a change that is about the prompt, not the picture --------------------


META = (
"VERDICT: fail\n"
"REASON: the prompt does not ask for an illustration\n"
'CHANGE: Add "in the style of an illustration" to the prompt\n'
'CHANGE: Add "with a solid background" to the prompt'
)


def test_a_note_about_the_prompt_becomes_the_instruction_it_meant(
        registry: Registry):
    """'Add X to the prompt' is how a judge says 'X'."""
    device = _device(registry, META)
    critique = Critic(device, JUDGE).judge(
        b"\x89PNG", RequirementVector(), "A friendly robot.")

    assert critique.suggested_changes == [
        "in the style of an illustration",
        "with a solid background",
    ]
    assert not any("the prompt" in change
                   for change in critique.suggested_changes), (
        "meta-text about the prompt cannot be sent to a model")


def test_a_change_still_about_the_prompt_is_dropped(registry: Registry):
    device = _device(registry, (
        "VERDICT: fail\n"
        "REASON: the prompt is wrong\n"
        "CHANGE: Rewrite the prompt to remove the contradictory instruction"
    ))
    critique = Critic(device, JUDGE).judge(
        b"\x89PNG", RequirementVector(), "A friendly robot.")

    assert critique.suggested_changes == []
    assert critique.inconclusive is True, (
        "a verdict with nothing actionable is inconclusive, not a failure")


def test_a_visible_change_is_left_alone(registry: Registry):
    """The filter must not eat real art direction."""
    device = _device(registry, (
        "VERDICT: fail\n"
        "REASON: the subject is too small\n"
        "CHANGE: make the subject larger in the frame"
    ))
    critique = Critic(device, JUDGE).judge(
        b"\x89PNG", RequirementVector(), "A friendly robot.")

    assert critique.suggested_changes == ["make the subject larger in the frame"]


# -- the agency -----------------------------------------------------------


def _agency(tmp_path, registry: Registry):
    from tis.config import Settings
    from tis.service import Agency

    settings = Settings(
        registry_path=REGISTRY_PATH,
        roles_path=ROLES_PATH,
        assets_dir=tmp_path / "assets",
        hold_file=tmp_path / "tiiny-hold",
        watchdog_lock=tmp_path / "tiiny-watch.lock",
        planner_model=JUDGE,
    )
    return Agency(settings, device=FakeDevice(registry,
                                              resident=[JUDGE, VISION_JUDGE]),
                  registry=registry)


def test_the_guide_lists_the_models_and_the_current_roles(tmp_path,
                                                          registry: Registry):
    agency = _agency(tmp_path, registry)
    options = agency.role_options()

    assert options["critic"]["model"] == VISION_JUDGE
    assert options["critic"]["vision"] is True
    assert options["models"], "the guide lists nothing"
    assert any(m["vision"] for m in options["models"])
    assert options["vision_models"], "the guide lists no vision-capable model"


def test_choosing_a_vision_critic_turns_the_vision_on(tmp_path,
                                                       registry: Registry):
    """The enabling half: the choice actually changes the judge."""
    agency = _agency(tmp_path, registry)
    result = agency.set_roles(critic=VISION_JUDGE)

    assert agency.critic.model_id == VISION_JUDGE
    assert agency.critic.vision is True
    assert result["critic"]["vision"] is True
    assert "SEE the image" in result["note"]


def test_choosing_a_blind_critic_is_refused(tmp_path, registry: Registry):
    """A judge that cannot see the image is not offered.

    A text-only critic judges the PROMPT, and a prompt judge does not
    fail loudly - it invents a defect, and every invented defect costs
    a generation. So the rule is that the judge SEES, and a model that
    cannot see is refused with the reason.
    """
    agency = _agency(tmp_path, registry)
    with pytest.raises(RoleError) as error:
        agency.set_roles(critic=JUDGE)

    message = str(error.value)
    assert "cannot see an image" in message
    assert "invent a defect" in message, (
        "the refusal has to say WHY, not just that it was refused")


def test_the_conversation_agent_may_still_be_a_text_model(
        tmp_path, registry: Registry):
    """Only the judge has to see. The talker reads text.

    The conversation agent writes the plan and never looks at a pixel,
    so a small text model is the right model for it - and a 27% one
    costs no swap at all because the watchdog already holds it.
    """
    agency = _agency(tmp_path, registry)
    agency.set_roles(conversation=JUDGE)
    assert agency.planner.model_id == JUDGE
    assert agency.critic.model_id == VISION_JUDGE, (
        "the talker changed the judge - the two roles are separate")


def test_choosing_the_conversation_agent_changes_the_planner(tmp_path,
                                                              registry: Registry):
    agency = _agency(tmp_path, registry)
    agency.set_roles(conversation=VISION_JUDGE)
    assert agency.planner.model_id == VISION_JUDGE


def test_a_model_outside_the_catalogue_is_refused(tmp_path, registry: Registry):
    agency = _agency(tmp_path, registry)
    with pytest.raises(RoleError):
        agency.set_roles(critic="nobody/imagines-this-model")


def test_the_judge_is_not_changed_when_nothing_was_asked(tmp_path,
                                                          registry: Registry):
    agency = _agency(tmp_path, registry)
    agency.set_roles()
    assert agency.critic.model_id == VISION_JUDGE
    assert agency.planner.model_id == JUDGE


# -- the fit --------------------------------------------------------------


def test_the_guide_says_whether_the_choice_fits(tmp_path, registry: Registry):
    """A guide that does not say whether the choice WORKS is a list."""
    agency = _agency(tmp_path, registry)
    fit = agency.role_options()["fit"]

    assert "generator" in fit
    # What has to be resident WHILE the image is judged: the judge and
    # the generator. The talker has already done its work by then.
    assert fit["total"] == fit["critic_npu"] + fit["generator_npu"]
    assert fit["during_judging"] == fit["total"]
    assert fit["ceiling"] == 81
    assert fit["fits"] == (fit["total"] <= fit["ceiling"])
    assert fit["advice"]


def test_the_talker_is_not_counted_against_the_pool_during_judging(
        tmp_path, registry: Registry):
    """The talker is swapped out while the image is made.

    Summing talker + judge + generator would say a 47% judge does not
    fit beside a 55% talker and a 23% generator (125%), and advise
    moving the talker to a smaller model. That advice is wrong: the
    talker's weights are gone by then, and 47% + 23% = 70% runs fine.
    """
    agency = _agency(tmp_path, registry)
    agency.set_roles(critic=VISION_JUDGE)
    fit = agency.role_options()["fit"]

    assert fit["conversation_npu"] == 55
    assert fit["critic_npu"] == 47
    assert fit["total"] == 70
    assert fit["fits"] is True
    assert "swapped out" in fit["advice"]


def test_the_judge_and_the_generator_must_fit_under_the_execution_ceiling(
        tmp_path, registry: Registry):
    """Not the admission ceiling. The device accepts 85% and then fails."""
    agency = _agency(tmp_path, registry)
    fit = agency.role_options()["fit"]

    assert fit["ceiling"] == 81, (
        "the ceiling is measured, not a policy knob: 81% ran, 85% did not")
    assert fit["total"] <= fit["ceiling"] or not fit["fits"]


def test_the_talker_has_to_be_on_the_device_to_be_swapped_back_in(
        tmp_path, registry: Registry):
    """A talker with no weights cannot answer the next request."""
    agency = _agency(tmp_path, registry)
    fit = agency.role_options()["fit"]
    assert fit["talker_downloaded"] is True


def test_one_model_holding_both_roles_is_counted_once(tmp_path,
                                                        registry: Registry):
    """When the talker and the judge are the same weights, they are
    counted once.

    A vision model can do both jobs, and then the pool pays for it once.
    """
    agency = _agency(tmp_path, registry)
    agency.set_roles(conversation=VISION_JUDGE)
    agency.set_roles(critic=VISION_JUDGE)
    fit = agency.role_options()["fit"]

    assert fit["shared_model"] is True
    assert fit["fits"] is True
    assert fit["total"] == fit["critic_npu"] + fit["generator_npu"]


def test_a_vision_judge_that_does_not_fit_is_told_how_to_fix_it(
        tmp_path, registry: Registry):
    """The advice is the whole point of the fit."""
    agency = _agency(tmp_path, registry)
    agency.set_roles(critic=VISION_JUDGE)
    fit = agency.role_options()["fit"]

    if not fit["fits"]:
        assert "A smaller judge would work" in fit["advice"]


def test_the_talker_size_does_not_change_the_verdict(tmp_path,
                                                      registry: Registry):
    """Swapping the talker for a smaller one changes nothing now.

    The talker is swapped out while the image is made, so its size is
    not part of the sum. This is the advice the first version of the
    guide got wrong: it told a user to move their talker to a smaller
    model when the judge was the thing that had to fit.
    """
    agency = _agency(tmp_path, registry)
    agency.set_roles(critic=VISION_JUDGE)
    tight = agency.role_options()["fit"]

    cheap = next((m for m in roles_all(registry)
                  if m.id == "Qwen/Qwen3.5-9B"), None)
    if cheap is None:
        return  # not on this store; nothing to check
    agency.set_roles(conversation=cheap.id)
    roomy = agency.role_options()["fit"]

    assert roomy["total"] == tight["total"], (
        "the talker's size is not part of the sum while judging")
    assert roomy["fits"] == tight["fits"]


def test_the_advice_never_claims_a_fit_it_did_not_check(tmp_path,
                                                          registry: Registry):
    """A recommendation with the arithmetic behind it.

    The first version of this recommended a model and then said "which
    fits" without doing the sum. It recommended one that gave 107%.
    """
    agency = _agency(tmp_path, registry)
    agency.set_roles(critic=VISION_JUDGE)
    fit = agency.role_options()["fit"]

    if "A smaller judge would work" in fit["advice"]:
        # Find the model it names, and check the sum it claims.
        named = fit["advice"].split("A smaller judge would work: ")[1]
        model_id = named.split(" would give")[0].strip()
        spec = agency.roles.get(model_id)
        assert spec is not None, f"the advice names {model_id}, which is not in the catalogue"
        assert spec.npu_usage + fit["generator_npu"] <= fit["ceiling"], (
            "the advice recommends a judge that does not fit")
        assert fit["fits"] is False


def roles_all(registry: Registry):
    return Roles.load(ROLES_PATH).all()


# -- the API --------------------------------------------------------------


def _client(agency):
    from fastapi.testclient import TestClient

    from tis.api import create_app

    return TestClient(create_app(agency=agency))


def test_the_guide_route_lists_the_models(tmp_path, registry: Registry):
    agency = _agency(tmp_path, registry)
    response = _client(agency).get("/v1/roles")

    assert response.status_code == 200
    body = response.json()
    assert body["critic"]["model"] == VISION_JUDGE
    assert body["models"]
    assert any(m["vision"] for m in body["models"])
    assert body["vision_models"], "the guide lists no vision-capable model"


def test_the_guide_route_says_whether_the_judge_can_see(tmp_path,
                                                          registry: Registry):
    agency = _agency(tmp_path, registry)
    body = _client(agency).get("/v1/roles").json()
    assert body["critic"]["vision"] is True, (
        "the judge must always be able to see the image")


def test_choosing_a_vision_critic_through_the_api(tmp_path,
                                                  registry: Registry):
    """The enable, over HTTP."""
    agency = _agency(tmp_path, registry)
    response = _client(agency).post("/v1/roles",
                                    json={"critic": VISION_JUDGE})

    assert response.status_code == 200
    assert agency.critic.model_id == VISION_JUDGE
    assert agency.critic.vision is True
    assert response.json()["critic"]["vision"] is True


def test_choosing_the_conversation_agent_through_the_api(tmp_path,
                                                          registry: Registry):
    agency = _agency(tmp_path, registry)
    response = _client(agency).post("/v1/roles",
                                    json={"conversation": VISION_JUDGE})
    assert response.status_code == 200
    assert agency.planner.model_id == VISION_JUDGE


def test_a_model_outside_the_catalogue_is_a_400(tmp_path,
                                                 registry: Registry):
    """A refusal, not a 500."""
    agency = _agency(tmp_path, registry)
    response = _client(agency).post("/v1/roles",
                                    json={"critic": "nobody/imagines-this"})
    assert response.status_code == 400
    assert "not in the conversational catalogue" in response.json()["detail"]


def test_the_roles_route_is_in_the_openapi_schema(tmp_path,
                                                  registry: Registry):
    agency = _agency(tmp_path, registry)
    schema = _client(agency).get("/openapi.json").json()
    assert "/v1/roles" in schema["paths"]
