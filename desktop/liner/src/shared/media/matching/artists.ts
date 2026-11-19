import { normalizeTrackString, toPhoneticLatin } from "./phonetic";

const KNOWN_ARTIST_ALIASES: Array<Set<string>> = [
  new Set(["в цой", "виктор цой", "цой", "кино"]),
  new Set([
    "горшок",
    "михаил горшенев",
    "князь",
    "андрей князев",
    "киш",
    "король и шут",
  ]),
  new Set(["лсп", "lsp"]),
  new Set(["пошлая молли", "poshlaya molly"]),
  new Set(["xxxmanera", "хххманера"]),
  new Set(["og buda", "ог буда"]),
  new Set(["scally milano", "скалли милано"]),
  new Set(["uglystephan", "аглистефан"]),
  new Set(["три дня дождя", "three days of rain"]),
  new Set([
    "miyagi",
    "мияги",
    "эндшпиль",
    "endspiel",
    "andy panda",
    "энди панда",
    "hajime",
  ]),
  new Set(["скриптонит", "scriptonite", "gruppa skryptonite"]),
  new Set(["pharaoh", "фараон"]),
  new Set(["boulevard depo", "бульвар депо"]),
  new Set(["saluki", "салуки"]),
  new Set(["markul", "маркул"]),
  new Set(["oxxxymiron", "оксимирон"]),
  new Set(["noize mc", "нойз мс"]),
  new Set(["валентин стрыкало", "юрий каплан", "стрыкало"]),
  new Set(["serebro", "серебро"]),
  new Set(["tatu", "t a t u", "тату"]),
  new Set(["macan", "макан"]),
  new Set(["kizaru", "кизару"]),
  new Set(["big baby tape", "биг бейби тейп", "bbtape"]),
  new Set(["егор крид", "egor kreed"]),
  new Set(["morgenshtern", "моргенштерн"]),
  new Set(["mc doni", "doni", "дони"]),
  new Set(["не будите спящих", "ne budite spyashchikh"]),
  new Set(["дискотека авария", "diskoteka avariya"]),
];

function containsEither(
  left: string,
  right: string,
  minLength: number,
): boolean {
  return (
    left.length >= minLength &&
    right.length >= minLength &&
    (left.includes(right) || right.includes(left))
  );
}

export function artistsMatch(
  sourceArtist: string,
  candidateArtist: string,
): boolean {
  if (!sourceArtist || !candidateArtist) return false;
  const sourceClean = normalizeTrackString(sourceArtist);
  const candidateClean = normalizeTrackString(candidateArtist);
  if (sourceClean.length > 0 && sourceClean === candidateClean) return true;

  const sourceCompact = sourceClean.replace(/\s+/g, "");
  const candidateCompact = candidateClean.replace(/\s+/g, "");
  if (sourceCompact.length > 0 && sourceCompact === candidateCompact)
    return true;

  if (
    KNOWN_ARTIST_ALIASES.some(
      (aliases) => aliases.has(sourceClean) && aliases.has(candidateClean),
    )
  )
    return true;
  if (containsEither(sourceCompact, candidateCompact, 3)) return true;

  const sourcePhonetic = toPhoneticLatin(sourceArtist);
  const candidatePhonetic = toPhoneticLatin(candidateArtist);
  if (sourcePhonetic.length > 0 && sourcePhonetic === candidatePhonetic)
    return true;
  return containsEither(sourcePhonetic, candidatePhonetic, 4);
}
