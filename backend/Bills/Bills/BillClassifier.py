import math
import pickle
import re
from collections import Counter
from pathlib import Path

import pdfplumber


def pdf_words_to_list(pdf_path):
    words = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_words = page.extract_words()
            if not page_words:
                continue

            for word_data in page_words:
                if "text" in word_data:
                    words.append(word_data["text"][::-1])

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


def extract_words_from_pdf(pdf_path):
    return clean_words(pdf_words_to_list(pdf_path))


def get_pdf_files(folder_path):
    return list(folder_path.glob("*.pdf"))


class SimpleBayesClassifier:
    def __init__(self):
        self.word_counts = {}
        self.total_words = {}
        self.document_counts = {}
        self.vocabulary = set()
        self.total_documents = 0

    def train_from_folders(self, folders):
        for label, folder_path in folders.items():
            self._train_label(label, folder_path)

    def _train_label(self, label, folder_path):
        counts = Counter()
        doc_count = 0

        for pdf_file in get_pdf_files(folder_path):
            try:
                words = extract_words_from_pdf(pdf_file)
                counts.update(words)
                self.vocabulary.update(words)
                doc_count += 1
            except Exception as e:
                print(f"Could not read {pdf_file}: {e}")

        self.word_counts[label] = counts
        self.total_words[label] = sum(counts.values())
        self.document_counts[label] = doc_count
        self.total_documents += doc_count

    def classify_text(self, text):
        words = clean_words(re.findall(r"[\w\u0590-\u05FF]+", text.lower()))
        log_probs = {}
        vocab_size = len(self.vocabulary)

        for label in self.word_counts:
            log_probs[label] = self._log_prob(label, words, vocab_size)

        prediction = max(log_probs, key=log_probs.get)
        return prediction, log_probs

    def _log_prob(self, label, words, vocab_size):
        prob_label = self.document_counts[label] / self.total_documents
        log_prob = math.log(prob_label)

        total_words_in_label = self.total_words[label]
        word_counts_in_label = self.word_counts[label]

        for word in words:
            count_word_in_label = word_counts_in_label.get(word, 0)
            prob_word_in_label = (count_word_in_label + 1) / (total_words_in_label + vocab_size)
            log_prob += math.log(prob_word_in_label)

        return log_prob


def save_model(classifier, model_path):
    with open(model_path, "wb") as f:
        pickle.dump(classifier, f)


def load_or_train_classifier(model_path, folders):
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


# Paths
Bills_PATH = Path.cwd() / "BillClassification" / "training_data" / "Bills"
Receipts_PATH = Path.cwd() / "BillClassification" / "training_data" / "reciepts"
MODEL_PATH = Path.cwd() / "trained_params.pkl"

FOLDERS = {
    "bills": Bills_PATH,
    "receipts": Receipts_PATH,
}

classifier = load_or_train_classifier(MODEL_PATH, FOLDERS)

TEST_PDF = Path.cwd() / "hebrew_invoice_receipt_sample_ezcount.pdf"

# extract words from pdf
pdf_words = extract_words_from_pdf(TEST_PDF)

# turn into text (space separated)
pdf_text = " ".join(pdf_words)

# classify
prediction, log_probs = classifier.classify_text(pdf_text)

print("Prediction:", prediction)
print("Log probabilities:", log_probs)