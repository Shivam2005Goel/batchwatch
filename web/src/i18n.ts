import type { Lang } from "./types";

/**
 * Three languages, three strings files.
 *
 * Half an hour of work, and it changes who the verdict screen actually
 * reaches. The advice text itself comes from the API (the backend owns the
 * severity-to-copy mapping so it cannot drift between clients).
 */
export const LANGS: { code: Lang; label: string }[] = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" },
  { code: "ta", label: "தமிழ்" },
];

type Dict = Record<string, string>;

const en: Dict = {
  "app.name": "BatchWatch",
  "app.tagline": "Has your medicine been recalled?",

  "nav.scan": "Scan",
  "nav.shelf": "Shelf",
  "nav.alerts": "Alerts",
  "nav.pharmacy": "Pharmacy",
  "nav.search": "Search",

  "scan.cta": "Photograph the strip",
  "scan.hint": "Point your camera at the batch number on the foil.",
  "scan.typeInstead": "Or type the label instead",
  "scan.typePlaceholder":
    "PARACETAMOL TABLETS IP 650mg\nB.No. KP4021H\nMFG 03/2026  EXP 02/2028\nMfd. by: ...",
  "scan.check": "Check this batch",
  "scan.reading": "Reading the strip",
  "scan.again": "Scan another",
  "scan.save": "Save to my shelf",
  "scan.saved": "Saved to your shelf",
  "scan.saving": "Saving",
  "scan.resized": "Resized {from}KB to {to}KB before upload",

  "verdict.batch": "Batch",
  "verdict.product": "Product",
  "verdict.manufacturer": "Manufacturer",
  "verdict.expiry": "Expiry",
  "verdict.reason": "Why it was flagged",
  "verdict.whatToDo": "What to do",
  "verdict.published": "Published",
  "verdict.confidence": "Match confidence",
  "verdict.source": "Regulator notice",
  "verdict.adjudicated": "Borderline read, checked again by the model",
  "verdict.expired": "This medicine is past its printed expiry date.",
  "verdict.whatWeRead": "What we read from the strip",

  "shelf.title": "My shelf",
  "shelf.empty": "Nothing saved yet.",
  "shelf.emptyHint": "Scan a medicine and save it. We will keep watching it for you.",
  "shelf.added": "Added",
  "shelf.remove": "Remove",
  "shelf.checking": "Checking against the latest alerts",

  "alerts.title": "Alerts",
  "alerts.empty": "Nothing you own has been flagged.",
  "alerts.emptyHint": "We will tell you if that changes.",
  "alerts.flaggedOn": "Flagged in the {month} alert",

  "pharmacy.title": "Pharmacy stock check",
  "pharmacy.hint":
    "Paste your stock list. One line per item: product, batch, manufacturer, expiry.",
  "pharmacy.check": "Check {n} lines",
  "pharmacy.checking": "Checking stock",
  "pharmacy.flagged": "Flagged",
  "pharmacy.uncertain": "Needs checking",
  "pharmacy.clear": "Not flagged",
  "pharmacy.skipped": "Skipped",
  "pharmacy.line": "Line",

  "search.title": "Search the alert list",
  "search.hint": "A batch number, a medicine, or a manufacturer.",
  "search.placeholder": "KP4021H or paracetamol",
  "search.results": "{n} results",
  "search.none": "Nothing in the published alerts matches that.",

  "common.loading": "Loading",
  "common.error": "Something went wrong",
  "common.retry": "Try again",
  "common.corpus": "{rows} flagged batches from {months} monthly alerts",
  "common.demoData": "Demo data - synthetic sample, not real regulator alerts",
};

const hi: Dict = {
  "app.tagline": "क्या आपकी दवा वापस मंगाई गई है?",
  "nav.scan": "स्कैन",
  "nav.shelf": "मेरी दवाइयाँ",
  "nav.alerts": "चेतावनी",
  "nav.pharmacy": "फार्मेसी",
  "nav.search": "खोजें",
  "scan.cta": "स्ट्रिप की फोटो लें",
  "scan.hint": "फॉइल पर छपे बैच नंबर पर कैमरा रखें।",
  "scan.typeInstead": "या लेबल टाइप करें",
  "scan.check": "यह बैच जाँचें",
  "scan.reading": "स्ट्रिप पढ़ी जा रही है",
  "scan.again": "दूसरी स्कैन करें",
  "scan.save": "मेरी सूची में सहेजें",
  "scan.saved": "सहेज लिया गया",
  "verdict.batch": "बैच",
  "verdict.product": "दवा",
  "verdict.manufacturer": "निर्माता",
  "verdict.expiry": "एक्सपायरी",
  "verdict.reason": "क्यों चिह्नित किया गया",
  "verdict.whatToDo": "क्या करें",
  "verdict.published": "प्रकाशित",
  "verdict.source": "नियामक सूचना",
  "verdict.whatWeRead": "स्ट्रिप से क्या पढ़ा गया",
  "shelf.title": "मेरी दवाइयाँ",
  "shelf.empty": "अभी कुछ सहेजा नहीं गया।",
  "shelf.emptyHint": "दवा स्कैन करके सहेजें। हम उस पर नज़र रखेंगे।",
  "shelf.remove": "हटाएँ",
  "alerts.title": "चेतावनी",
  "alerts.empty": "आपकी किसी दवा को चिह्नित नहीं किया गया है।",
  "alerts.emptyHint": "अगर ऐसा होता है तो हम आपको बताएँगे।",
  "pharmacy.title": "फार्मेसी स्टॉक जाँच",
  "search.title": "चेतावनी सूची खोजें",
  "search.hint": "बैच नंबर, दवा का नाम, या निर्माता।",
  "common.loading": "लोड हो रहा है",
  "common.error": "कुछ गड़बड़ हुई",
  "common.retry": "फिर कोशिश करें",
};

const ta: Dict = {
  "app.tagline": "உங்கள் மருந்து திரும்பப் பெறப்பட்டதா?",
  "nav.scan": "ஸ்கேன்",
  "nav.shelf": "என் மருந்துகள்",
  "nav.alerts": "எச்சரிக்கை",
  "nav.pharmacy": "மருந்தகம்",
  "nav.search": "தேடு",
  "scan.cta": "ஸ்ட்ரிப்பைப் படம் எடுங்கள்",
  "scan.hint": "ஃபாயிலில் உள்ள batch எண்ணில் கேமராவை வையுங்கள்.",
  "scan.typeInstead": "அல்லது லேபிளைத் தட்டச்சு செய்யுங்கள்",
  "scan.check": "இந்த batch-ஐச் சரிபார்க்கவும்",
  "scan.reading": "ஸ்ட்ரிப் படிக்கப்படுகிறது",
  "scan.again": "மற்றொன்றை ஸ்கேன் செய்",
  "scan.save": "என் பட்டியலில் சேமி",
  "scan.saved": "சேமிக்கப்பட்டது",
  "verdict.batch": "Batch",
  "verdict.product": "மருந்து",
  "verdict.manufacturer": "தயாரிப்பாளர்",
  "verdict.expiry": "காலாவதி",
  "verdict.reason": "ஏன் குறிக்கப்பட்டது",
  "verdict.whatToDo": "என்ன செய்ய வேண்டும்",
  "verdict.published": "வெளியிடப்பட்டது",
  "verdict.source": "ஒழுங்குமுறை அறிவிப்பு",
  "verdict.whatWeRead": "ஸ்ட்ரிப்பில் இருந்து படித்தது",
  "shelf.title": "என் மருந்துகள்",
  "shelf.empty": "இதுவரை எதுவும் சேமிக்கப்படவில்லை.",
  "shelf.emptyHint": "ஒரு மருந்தை ஸ்கேன் செய்து சேமியுங்கள். நாங்கள் கவனித்துக்கொள்கிறோம்.",
  "shelf.remove": "நீக்கு",
  "alerts.title": "எச்சரிக்கை",
  "alerts.empty": "உங்கள் மருந்துகள் எதுவும் குறிக்கப்படவில்லை.",
  "alerts.emptyHint": "அது மாறினால் நாங்கள் சொல்வோம்.",
  "pharmacy.title": "மருந்தக இருப்புச் சரிபார்ப்பு",
  "search.title": "எச்சரிக்கைப் பட்டியலில் தேடு",
  "search.hint": "Batch எண், மருந்து, அல்லது தயாரிப்பாளர்.",
  "common.loading": "ஏற்றுகிறது",
  "common.error": "ஏதோ தவறு நடந்தது",
  "common.retry": "மீண்டும் முயற்சி",
};

const DICTS: Record<Lang, Dict> = { en, hi, ta };

/** Falls back to English for any string not yet translated. */
export function t(lang: Lang, key: string, vars: Record<string, string | number> = {}): string {
  const raw = DICTS[lang][key] ?? en[key] ?? key;
  return raw.replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? `{${name}}`));
}

export function storedLang(): Lang {
  const saved = localStorage.getItem("bw.lang");
  return saved === "hi" || saved === "ta" ? saved : "en";
}

export function storeLang(lang: Lang) {
  localStorage.setItem("bw.lang", lang);
}
