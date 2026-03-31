import math
import pickle
import re
from collections import Counter
from pathlib import Path

import pdfplumber


def pdf_words_to_list(pdf_path: Path):
    words = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_words = page.extract_words()
            if not page_words:
                continue

            for word_data in page_words:
                if "text" in word_data:
                    # kept as in your original code, for Hebrew PDFs
                    words.append(word_data["text"][::-1])
    print('pdf: ',words[:10])
    return words


def txt_words_to_list(txt_path: Path):
    text = txt_path.read_text(encoding="utf-8", errors="replace")

    words = text.split()

    # reverse each word (Hebrew fix)

    print('text: ',words[:10])
    return words


def clean_words(words):
    cleaned = []

    for word in words:
        word = word.strip().lower()
        word = re.sub(r"[^\w\u0590-\u05FF]", "", word)

        if not word:
            continue

        if re.fullmatch(r"\d+", word):
            continue

        cleaned.append(word)

    return cleaned


def extract_words_from_pdf(pdf_path: Path):
    return clean_words(pdf_words_to_list(pdf_path))


def extract_words_from_txt(txt_path: Path):
    return clean_words(txt_words_to_list(txt_path))


def extract_words_from_file(file_path: Path):
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return extract_words_from_pdf(file_path)

    if suffix == ".txt":
        return extract_words_from_txt(file_path)

    raise ValueError(f"Unsupported file type: {file_path}")


def get_document_files(folder_path: Path):
    return [
        p for p in folder_path.iterdir()
        if p.is_file() and p.suffix.lower() in {".pdf", ".txt"}
    ]


class SimpleBayesClassifier:
    def __init__(self):
        self.word_counts = {}
        self.total_words = {}
        self.document_counts = {}
        self.vocabulary = set()
        self.total_documents = 0

    def train_from_folders(self, folders):
        self.word_counts = {}
        self.total_words = {}
        self.document_counts = {}
        self.vocabulary = set()
        self.total_documents = 0

        for label, folder_path in folders.items():
            self._train_label(label, Path(folder_path))

    def _train_label(self, label, folder_path: Path):
        counts = Counter()
        doc_count = 0

        for file_path in get_document_files(folder_path):
            try:
                words = extract_words_from_file(file_path)
                if not words:
                    continue

                counts.update(words)
                self.vocabulary.update(words)
                doc_count += 1

            except Exception as e:
                print(f"Could not read {file_path}: {e}")

        self.word_counts[label] = counts
        self.total_words[label] = sum(counts.values())
        self.document_counts[label] = doc_count
        self.total_documents += doc_count

    def classify_text(self, text: str):
        words = clean_words(re.findall(r"[\w\u0590-\u05FF]+", text.lower()))
        return self._classify_words(words)

    def classify_file(self, file_path: Path):
        words = extract_words_from_file(Path(file_path))
        return self._classify_words(words)

    def _classify_words(self, words):
        if not self.word_counts:
            raise ValueError("Classifier is not trained.")

        if self.total_documents == 0:
            raise ValueError("Classifier has no training documents.")

        log_probs = {}
        vocab_size = len(self.vocabulary)

        for label in self.word_counts:
            log_probs[label] = self._log_prob(label, words, vocab_size)

        prediction = max(log_probs, key=log_probs.get)
        return prediction, log_probs

    def _log_prob(self, label, words, vocab_size):
        label_doc_count = self.document_counts.get(label, 0)
        if label_doc_count == 0:
            return float("-inf")

        prob_label = label_doc_count / self.total_documents
        log_prob = math.log(prob_label)

        total_words_in_label = self.total_words[label]
        word_counts_in_label = self.word_counts[label]

        for word in words:
            count_word_in_label = word_counts_in_label.get(word, 0)
            prob_word_in_label = (count_word_in_label + 1) / (total_words_in_label + vocab_size)
            log_prob += math.log(prob_word_in_label)

        return log_prob


def save_model(classifier, model_path: Path):
    with open(model_path, "wb") as f:
        pickle.dump(classifier, f)


def load_or_train_classifier(model_path: Path, folders):
    if model_path.exists():
        print("Loading model...")
        with open(model_path, "rb") as f:
            return pickle.load(f)

    print("Training model...")
    classifier = SimpleBayesClassifier()
    classifier.train_from_folders(folders)
    save_model(classifier, model_path)
    print("Model saved to", model_path)
    return classifier

# classifier = load_or_train_classifier(MODEL_PATH, FOLDERS)
def get_financial_vs_general_classifier():
    model_path = Path.cwd() /'Bills' /"financial_vs_general_trained_params.pkl"
    print(model_path)
    folders = {
        "general": Path.cwd() /'Bills'/ "BillClassification" / "training_data" / "financial_vs_general" / "general",
        "financial": Path.cwd() /'Bills' / "BillClassification" / "training_data" / "financial_vs_general" / "financial",
    }
    return load_or_train_classifier(model_path, folders)

