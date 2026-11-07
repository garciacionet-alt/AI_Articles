"""The resolver, driven from the acceptance spec.

Every expectation lives in app/tests/resolver_acceptance.py — the spec file is
the source of truth and is imported, never restated. This module only wires
the spec's cases to the implementation.
"""
from __future__ import annotations

import json

import pytest

from resolver_acceptance import (
    CASES,
    OCCUPANCY_CASES,
    REFUSAL_CASES,
    REGISTRY,
    normalize,
    occupancy,
)

from tis.models import RequirementVector
from tis.registry import COMMUNITY_MODEL_IDS, Registry
from tis.resolver import Resolver, ResolverError


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(REGISTRY)


@pytest.fixture(scope="module")
def resolver(registry: Registry) -> Resolver:
    return Resolver(registry)


@pytest.fixture(scope="module")
def raw_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _vector(req: dict) -> RequirementVector:
    return RequirementVector(**normalize(req))


@pytest.mark.parametrize(
    "name,req,expected",
    CASES,
    ids=[case[0] for case in CASES],
)
def test_selection_matches_the_spec(name, req, expected, resolver: Resolver):
    """Every selection case in the spec resolves to the spec's winner."""
    assert resolver.resolve(_vector(req)).chosen.id == expected


@pytest.mark.parametrize(
    "name,req,expected_model,expected_pct,expected_resident,expected_exceeds",
    OCCUPANCY_CASES,
    ids=[case[0] for case in OCCUPANCY_CASES],
)
def test_occupancy_matches_the_spec(
    name,
    req,
    expected_model,
    expected_pct,
    expected_resident,
    expected_exceeds,
    resolver: Resolver,
    raw_registry: dict,
):
    """Occupancy, planner residency and the ceiling flag match the spec."""
    resolution = resolver.resolve(_vector(req))

    assert resolution.chosen.id == expected_model
    assert resolution.generation_occupancy_pct == expected_pct
    assert resolution.planner_resident == expected_resident
    assert resolution.exceeds_measured_ceiling == expected_exceeds

    # The spec's own occupancy function is the cross-check.
    assert (
        resolution.generation_occupancy_pct,
        resolution.planner_resident,
        resolution.exceeds_measured_ceiling,
    ) == occupancy(expected_model, raw_registry)


def test_community_build_is_never_chosen(resolver: Resolver):
    """A community build is never selected, in any case."""
    for name, req, _expected in CASES:
        assert resolver.resolve(_vector(req)).chosen.id not in COMMUNITY_MODEL_IDS


def test_community_build_surfaces_as_unavailable(resolver: Resolver):
    """For an alpha-required icon the community build is named, but only as
    unavailable.

    It is not downloaded on the appliance, so it cannot be loaded, and it
    is not a vendor build either. It surfaces in `unavailable` with the
    reason, not in `alternatives` where a caller might try to use it.
    """
    resolution = resolver.resolve(_vector(dict(artifact="icon", alpha="required")))

    alternative_ids = [alternative.id for alternative in resolution.alternatives]
    assert "abenzerps/Qwen-Image-2.1-Uncensored-Quantized" not in alternative_ids

    unavailable_ids = [model.id for model in resolution.unavailable]
    assert "abenzerps/Qwen-Image-2.1-Uncensored-Quantized" in unavailable_ids

    assert "not downloaded" in resolution.justification


def test_a_model_that_is_not_downloaded_is_never_chosen(resolver: Resolver):
    """No case may select a model the appliance cannot load."""
    for name, req, _expected in CASES:
        resolution = resolver.resolve(_vector(req))
        assert resolution.chosen.downloaded, (
            f"{name} chose {resolution.chosen.id}, which is not downloaded")


@pytest.mark.parametrize(
    "name,req,missing_model",
    REFUSAL_CASES,
    ids=[case[0] for case in REFUSAL_CASES],
)
def test_a_refusal_names_the_model_to_download(name, req, missing_model,
                                                resolver: Resolver):
    """A request only an undownloaded model can do is refused, and the
    refusal says what to download.

    Falling back to a model that cannot do the job would produce an
    image that silently fails the request — worse than an error.
    """
    with pytest.raises(ResolverError) as error:
        resolver.resolve(_vector(req))

    message = str(error.value)
    assert missing_model in message
    assert "download" in message.lower()


def test_alternatives_never_contain_the_chosen_model(resolver: Resolver):
    """The chosen model is not also an alternative."""
    for name, req, _expected in CASES:
        resolution = resolver.resolve(_vector(req))
        assert resolution.chosen.id not in [a.id for a in resolution.alternatives]


def test_resolving_is_deterministic(resolver: Resolver):
    """The same input twice gives the same Resolution."""
    for name, req, _expected in CASES:
        assert resolver.resolve(_vector(req)) == resolver.resolve(_vector(req))


def test_justification_names_the_model_and_the_occupancy(resolver: Resolver):
    """A developer reading the response can see what was picked and at what cost."""
    for name, req, _expected in CASES:
        resolution = resolver.resolve(_vector(req))
        assert resolution.chosen.id in resolution.justification
        assert str(resolution.generation_occupancy_pct) in resolution.justification


def test_swap_plan_is_well_formed(resolver: Resolver, registry: Registry):
    """load and keep never overlap, and the planner is evicted when it cannot stay."""
    for name, req, _expected in CASES:
        resolution = resolver.resolve(_vector(req))
        plan = resolution.swap_plan

        assert set(plan) == {"load", "evict", "keep"}
        assert not set(plan["keep"]) & set(plan["load"])
        assert resolution.swap_required == bool(plan["load"] or plan["evict"])

        if not resolution.planner_resident:
            assert registry.planner.id in plan["evict"]


def test_unknown_artifact_still_resolves(resolver: Resolver):
    """A request for an artifact no model declares still gets a model.

    The registry's artifact lists are a model's declared speciality, not a
    closed vocabulary of what a user may ask for. The resolver falls back to
    the whole catalogue rather than refusing the request.
    """
    resolution = resolver.resolve(RequirementVector(artifact="blueprint"))
    assert resolution.chosen.id
    assert resolution.justification
    assert resolution.chosen.id not in COMMUNITY_MODEL_IDS
