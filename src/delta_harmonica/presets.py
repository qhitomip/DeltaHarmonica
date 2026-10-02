"""Built-in quest melody fragments and their physical game keys."""
from dataclasses import dataclass

from .game_io import GameKey, NOTE_KEYS, ToneBand
from .midi import MidiNote

SOURCE_URL = 'https://3g.ali213.net/gl/html/1807561.html'
NORMAL_SECONDS = 0.35
LONG_SECONDS = 1.20
GAP_SECONDS = 0.15


@dataclass(frozen=True)
class QuestPreset:
    id: str
    title: str
    # Degree, mouse band, long-note marker. Keep exact physical task keys.
    phrase: tuple[tuple[int, ToneBand, bool], ...]
    hint: str

    def performance(self) -> tuple[list[MidiNote], list[GameKey]]:
        notes, keys = [], []
        start = 0.0
        degrees = (0, 2, 4, 5, 7, 9, 11, 12)
        offsets = {ToneBand.NATURAL: 0, ToneBand.LOW: -12,
                   ToneBand.HIGH: 12, ToneBand.SEMITONE: 1}
        for degree, band, long in self.phrase:
            duration = LONG_SECONDS if long else NORMAL_SECONDS
            notes.append(MidiNote(start, duration, 60 + degrees[degree - 1] + offsets[band]))
            keys.append(GameKey(band, NOTE_KEYS[degree - 1], str(degree)))
            start = round(start + duration + GAP_SECONDS, 6)
        return notes, keys


N, L, H = ToneBand.NATURAL, ToneBand.LOW, ToneBand.HIGH

def phrase(digits: str, band=ToneBand.NATURAL):
    return tuple((int(digit), band, False) for digit in digits)


_HINT = '自行接取风声未止并进入复奏界面，F6 吹奏后自行提交。'
PRESETS = (
    QuestPreset('builtin:shouwang', '夜莺 · 佐拉任务片段',
                phrase('767') + ((6, N, True),) + phrase('354'), _HINT),
    QuestPreset('builtin:yeying', '守望 · 老乔任务片段',
                phrase('5', L) + phrase('123543123'), _HINT),
    QuestPreset('builtin:fengqi', '风起 · 唐吉任务片段',
                phrase('67', L) + phrase('121') + phrase('7', L) + phrase('1'), _HINT),
    QuestPreset('builtin:poxiao', '破晓 · 佐拉任务片段',
                phrase('7636767') + phrase('1434', H),
                '先学会前三首，再新开一局找佐拉。' + _HINT),
)


def find_preset(song_id: str) -> QuestPreset | None:
    return next((preset for preset in PRESETS if preset.id == song_id), None)
