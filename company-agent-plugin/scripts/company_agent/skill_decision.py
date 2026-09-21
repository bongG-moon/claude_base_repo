"""Finite, local preparation decisions over a verified catalogue snapshot.

Retrieval is evidence, not semantic certainty. This layer has no I/O, model,
permission decision, skill-body loading, or execution side effect.
"""
from dataclasses import dataclass


NEXT_ACTIONS = {
    'inspect': 'inspect-catalog', 'general': 'general-if-no-relevant-skill',
    'review': 'compare-available-list', 'choose': 'ask-skill-choice',
    'select': 'compare-relevant-workflows', 'load': 'load-relevant-skill',
    'reuse': 'apply-selected-skill',
}


@dataclass(frozen=True)
class SkillDecision:
    mode: str
    reason: str
    candidate_id: str | None = None
    choice_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.mode, str) or self.mode not in NEXT_ACTIONS or not isinstance(self.reason, str) or not self.reason:
            raise ValueError('Invalid skill preparation decision')
        if self.candidate_id is not None and (not isinstance(self.candidate_id, str) or not self.candidate_id):
            raise ValueError('Invalid candidate identity')
        if (self.mode in {'load', 'reuse'}) != bool(self.candidate_id):
            raise ValueError('Only a concrete load/reuse decision has a candidate')
        if self.choice_ids and (self.mode != 'choose' or len(self.choice_ids) < 2):
            raise ValueError('Only competing choices have required candidate identities')

    def plan(self) -> dict:
        result = {'mode': self.mode, 'reason': self.reason}
        if self.candidate_id:
            result['id'] = self.candidate_id
        if self.choice_ids:
            result['choiceIds'] = list(self.choice_ids)
        return result


def decide_preparation(hints: dict, skills: list[dict], explicit: list[str]) -> SkillDecision:
    """Compose small checks; missing, ambiguous and unknown remain distinct.

    The caller validates catalogue identity/revision first. A unique candidate
    is a suggestion to load, NOT a command to execute or a claim of relevance.
    """
    if not isinstance(hints, dict) or hints.get('status') in ('incomplete', 'check-catalog'):
        return SkillDecision('inspect', 'catalog-not-complete')
    eligible = [row for row in skills if not row.get('incoming') and
                (not row.get('explicitOnly') or row.get('invocation') in explicit)]
    if not eligible:
        return SkillDecision('general', 'no-eligible-catalog-skills')
    groups = hints.get('groups', [])
    if not isinstance(groups, list) or any(not isinstance(group, dict) for group in groups):
        return SkillDecision('inspect', 'invalid-candidate-metadata')
    if not groups:
        return SkillDecision('review', 'shortlist-miss-not-skill-absence')
    # Exact user choice beats other names found by retrieval. Do not guess
    # between two explicitly invoked Skills or two origins of one invocation.
    named = [g['candidates'][0]['id'] for g in groups if g.get('resolution') == 'explicit'
             and isinstance(g.get('candidates'), list) and len(g['candidates']) == 1
             and isinstance(g['candidates'][0], dict) and g['candidates'][0].get('id')]
    if len(named) == 1 and sum(row.get('id') == named[0] for row in eligible) == 1:
        return SkillDecision('load', 'explicit-choice', named[0])
    competition = hints.get('competingIds', [])
    if (isinstance(competition, list) and 1 < len(competition) <= 8
            and all(isinstance(value, str) for value in competition)
            and len(set(competition)) == len(competition)
            and all(sum(row.get('id') == value for row in eligible) == 1 for value in competition)):
        return SkillDecision('choose', 'competing-workflows', choice_ids=tuple(competition))
    if hints.get('status') == 'needs-choice':
        return SkillDecision('choose', 'overlap-or-stale-preference')
    if len(groups) != 1 or type(hints.get('matchingGroups')) is not int or hints.get('matchingGroups') != 1 or hints.get('moreInCatalog'):
        return SkillDecision('select', 'compare-relevant-workflows')
    group = groups[0]
    options = group.get('candidates', [])
    if not isinstance(options, list) or any(not isinstance(row, dict) for row in options):
        return SkillDecision('inspect', 'invalid-candidate-metadata')
    if group.get('resolution') not in ('available', 'selected', 'explicit') or len(options) != 1:
        return SkillDecision('choose', 'unresolved-choice')
    candidate_id = options[0].get('id')
    if (not isinstance(candidate_id, str) or not candidate_id or
            sum(row.get('id') == candidate_id for row in skills) != 1 or
            not any(row.get('id') == candidate_id for row in eligible)):
        return SkillDecision('inspect', 'candidate-not-eligible')
    return SkillDecision('load', 'native-body-load', candidate_id)
