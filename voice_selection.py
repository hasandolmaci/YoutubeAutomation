"""Choose a narrator voice from first-person clues, with an auditable reason."""
import re


def select_voice(story, default='af_heart'):
    override = story.get('narrator_gender', '').lower()
    text = story.get('title', '') + '. ' + story.get('text', '')
    # Quoted characters must not determine the narrator's identity.
    text = re.sub(r'"[^"\n]*"|“[^”\n]*”', '', text)
    explicit = set()
    if override in ('male', 'female'):
        explicit.add(override)
    age_patterns = [r'\b(?:i(?: am|[’\x27]m)?|my)\s*[\[(]?\s*(\d{1,2})\s*([mf])\b',
                    r'^\s*[\[(]?\s*(\d{1,2})\s*([mf])\b']
    for content in (text, story.get('text', '')):
        for pattern in age_patterns:
            for match in re.finditer(pattern, content, re.I):
                explicit.add('male' if match[2].lower() == 'm' else 'female')
    for gender, pattern in [('male', r'\bi(?: am|[’\x27]m) (?:a |an )?(?:man|male|guy|husband|father)\b'),
                            ('female', r'\bi(?: am|[’\x27]m) (?:a |an )?(?:woman|female|wife|mother)\b')]:
        if re.search(pattern, text, re.I): explicit.add(gender)
    if len(explicit) == 1:
        gender = explicit.pop()
        return ('am_michael' if gender == 'male' else 'af_heart'), 'explicit ' + gender + ' narrator clue'
    if len(explicit) > 1:
        return default, 'conflicting clues; channel default'
    # Relationship inference is a fallback requested for this project, not certainty.
    male = bool(re.search(r'\bmy (?:girlfriend|gf|wife)\b', text, re.I))
    female = bool(re.search(r'\bmy (?:boyfriend|bf|husband)\b', text, re.I))
    if male and not female:
        return 'am_michael', 'relationship inference: my girlfriend/gf/wife'
    if female and not male:
        return 'af_heart', 'relationship inference: my boyfriend/bf/husband'
    return default, 'no clear narrator clue; channel default'
