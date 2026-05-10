import math
import pickle
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
import joblib
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

class naivebayesclasify():
    def __init__(self):


x_train = []

