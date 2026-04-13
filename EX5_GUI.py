#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import re
import tkinter as tk
import unicodedata
from tkinter import ttk, filedialog, messagebox
from collections import defaultdict
from dataclasses import dataclass, field
from typing import DefaultDict, Dict, List, Set, Tuple


def remove_vietnamese_accents(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def tokenize(text: str) -> List[str]:
    return re.findall(r"\w+", text, flags=re.UNICODE)


@dataclass
class InvertedIndex:
    doc_table: Dict[int, str] = field(default_factory=dict)

    # Chỉ mục theo dạng có dấu đã chuẩn hóa
    exact_term_table: DefaultDict[str, Dict[int, int]] = field(
        default_factory=lambda: defaultdict(dict)
    )

    # Chỉ mục theo dạng không dấu
    accentless_term_table: DefaultDict[str, Dict[int, int]] = field(
        default_factory=lambda: defaultdict(dict)
    )

    stop_words_exact: Set[str] = field(default_factory=set)
    stop_words_accentless: Set[str] = field(default_factory=set)

    def normalize_exact(self, word: str) -> str:
        word = word.strip().lower()
        if not word:
            return ""
        word = "".join(ch for ch in word if ch.isalnum())
        return word

    def normalize_accentless(self, word: str) -> str:
        word = self.normalize_exact(word)
        if not word:
            return ""
        return remove_vietnamese_accents(word)

    def load_stoplist(self, stoplist_path: str) -> None:
        self.stop_words_exact.clear()
        self.stop_words_accentless.clear()

        with open(stoplist_path, "r", encoding="utf-8") as f:
            for line in f:
                for token in tokenize(line):
                    exact = self.normalize_exact(token)
                    accentless = self.normalize_accentless(token)
                    if exact:
                        self.stop_words_exact.add(exact)
                    if accentless:
                        self.stop_words_accentless.add(accentless)

    def create_index(self, directory: str, stoplist_filename: str) -> None:
        self.doc_table.clear()
        self.exact_term_table.clear()
        self.accentless_term_table.clear()

        if not os.path.isdir(directory):
            raise NotADirectoryError(f"Không tìm thấy thư mục: {directory}")

        stoplist_path = os.path.join(directory, stoplist_filename)
        if not os.path.exists(stoplist_path):
            raise FileNotFoundError(f"Không tìm thấy file StopList: {stoplist_path}")

        self.load_stoplist(stoplist_path)

        files = sorted(os.listdir(directory))
        doc_id = 1

        for filename in files:
            full_path = os.path.join(directory, filename)

            if not os.path.isfile(full_path):
                continue
            if filename == stoplist_filename or filename.lower() == "query.txt":
                continue
            if not filename.lower().endswith(".txt"):
                continue

            self.doc_table[doc_id] = filename

            with open(full_path, "r", encoding="utf-8") as f:
                text = f.read()

            freq_exact: DefaultDict[str, int] = defaultdict(int)
            freq_accentless: DefaultDict[str, int] = defaultdict(int)

            for raw_token in tokenize(text):
                exact = self.normalize_exact(raw_token)
                accentless = self.normalize_accentless(raw_token)

                if not exact or not accentless:
                    continue

                # Vẫn giữ đúng tinh thần đề: chỉ lấy từ bắt đầu bằng C/c
                first_char = accentless[0].lower()
                if first_char != "c":
                    continue

                if exact in self.stop_words_exact or accentless in self.stop_words_accentless:
                    continue

                freq_exact[exact] += 1
                freq_accentless[accentless] += 1

            for term, freq in freq_exact.items():
                self.exact_term_table[term][doc_id] = freq

            for term, freq in freq_accentless.items():
                self.accentless_term_table[term][doc_id] = freq

            doc_id += 1

    def find_word(self, word: str, n: int) -> List[Tuple[int, str, int, str]]:
        """
        Trả về:
        (doc_id, filename, score, match_type)

        match_type:
        - "exact"      : khớp đúng có dấu / đúng chính tả
        - "accentless" : khớp theo dạng không dấu
        """
        exact = self.normalize_exact(word)
        accentless = self.normalize_accentless(word)

        if not exact or not accentless:
            return []

        results_map: Dict[int, Tuple[int, str, int, str]] = {}

        # 1. Ưu tiên khớp đúng trước
        exact_postings = self.exact_term_table.get(exact, {})
        for doc_id, freq in exact_postings.items():
            results_map[doc_id] = (doc_id, self.doc_table[doc_id], freq, "exact")

        # 2. Nếu có dạng không dấu, bổ sung các tài liệu chưa có
        accentless_postings = self.accentless_term_table.get(accentless, {})
        for doc_id, freq in accentless_postings.items():
            if doc_id not in results_map:
                results_map[doc_id] = (doc_id, self.doc_table[doc_id], freq, "accentless")

        results = list(results_map.values())

        # exact đứng trước, sau đó mới accentless; cùng loại thì sort theo score giảm dần
        results.sort(key=lambda x: (0 if x[3] == "exact" else 1, -x[2], x[1]))
        return results[:n]

    def find_wordfile(self, wordfile_path: str, n: int) -> List[Tuple[int, str, int]]:
        if not os.path.exists(wordfile_path):
            raise FileNotFoundError(f"Không tìm thấy WordFile: {wordfile_path}")

        doc_scores: DefaultDict[int, int] = defaultdict(int)

        with open(wordfile_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                word = line.strip()
                if not word:
                    continue

                parts = word.split()
                if len(parts) != 1:
                    raise ValueError(
                        f"Dòng {line_no} trong WordFile không hợp lệ. "
                        f"Mỗi dòng chỉ được chứa 1 từ."
                    )

                exact = self.normalize_exact(parts[0])
                accentless = self.normalize_accentless(parts[0])

                if not exact or not accentless:
                    continue

                # Cộng điểm exact trước
                exact_postings = self.exact_term_table.get(exact, {})
                for doc_id, freq in exact_postings.items():
                    doc_scores[doc_id] += freq

                # Cộng thêm accentless cho các tài liệu chưa có exact của từ đó
                accentless_postings = self.accentless_term_table.get(accentless, {})
                for doc_id, freq in accentless_postings.items():
                    if doc_id not in exact_postings:
                        doc_scores[doc_id] += freq

        results = [
            (doc_id, self.doc_table[doc_id], score)
            for doc_id, score in doc_scores.items()
            if score > 0
        ]
        results.sort(key=lambda x: (-x[2], x[1]))
        return results[:n]

    def index_text(self) -> str:
        lines = ["===== DocTable ====="]
        for doc_id, filename in self.doc_table.items():
            lines.append(f"{doc_id}: {filename}")

        lines.append("")
        lines.append("===== Exact TermTable =====")
        for term in sorted(self.exact_term_table.keys()):
            postings = self.exact_term_table[term]
            posting_str = ", ".join(
                f"(doc={doc_id}, freq={freq})"
                for doc_id, freq in sorted(postings.items())
            )
            lines.append(f"{term}: {posting_str}")

        lines.append("")
        lines.append("===== Accentless TermTable =====")
        for term in sorted(self.accentless_term_table.keys()):
            postings = self.accentless_term_table[term]
            posting_str = ", ".join(
                f"(doc={doc_id}, freq={freq})"
                for doc_id, freq in sorted(postings.items())
            )
            lines.append(f"{term}: {posting_str}")

        return "\n".join(lines)


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("EX5 - Inverted Index GUI (Tiếng Việt có dấu / không dấu)")
        self.root.geometry("1140x740")

        self.index = InvertedIndex()

        self.directory_var = tk.StringVar()
        self.stoplist_var = tk.StringVar(value="stoplist.txt")
        self.word_var = tk.StringVar()
        self.topn_var = tk.StringVar(value="5")
        self.queryfile_var = tk.StringVar()

        self._build_ui()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        setup = ttk.LabelFrame(main, text="Thiết lập dữ liệu", padding=10)
        setup.pack(fill="x", pady=(0, 10))

        ttk.Label(setup, text="Thư mục dữ liệu:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        ttk.Entry(setup, textvariable=self.directory_var, width=72).grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        ttk.Button(setup, text="Chọn thư mục", command=self.choose_directory).grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(setup, text="Stoplist:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        ttk.Entry(setup, textvariable=self.stoplist_var, width=30).grid(row=1, column=1, sticky="w", padx=5, pady=5)
        ttk.Button(setup, text="Tạo chỉ mục", command=self.create_index).grid(row=1, column=2, padx=5, pady=5)
        setup.columnconfigure(1, weight=1)

        query_frame = ttk.Frame(main)
        query_frame.pack(fill="x", pady=(0, 10))

        one_word = ttk.LabelFrame(query_frame, text="Tìm 1 từ", padding=10)
        one_word.pack(side="left", fill="both", expand=True, padx=(0, 5))

        ttk.Label(one_word, text="Từ truy vấn:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        ttk.Entry(one_word, textvariable=self.word_var, width=30).grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        ttk.Label(one_word, text="Top N:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        ttk.Entry(one_word, textvariable=self.topn_var, width=10).grid(row=1, column=1, sticky="w", padx=5, pady=5)
        ttk.Button(one_word, text="Tìm 1 từ", command=self.search_word).grid(row=2, column=0, columnspan=2, pady=8)
        one_word.columnconfigure(1, weight=1)

        multi_word = ttk.LabelFrame(query_frame, text="Tìm bằng file query", padding=10)
        multi_word.pack(side="left", fill="both", expand=True, padx=(5, 0))

        ttk.Label(multi_word, text="File query:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        ttk.Entry(multi_word, textvariable=self.queryfile_var, width=38).grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        ttk.Button(multi_word, text="Chọn file", command=self.choose_queryfile).grid(row=0, column=2, padx=5, pady=5)
        ttk.Label(multi_word, text="Top N:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        ttk.Entry(multi_word, textvariable=self.topn_var, width=10).grid(row=1, column=1, sticky="w", padx=5, pady=5)
        ttk.Button(multi_word, text="Tìm bằng file", command=self.search_wordfile).grid(row=2, column=0, columnspan=3, pady=8)
        multi_word.columnconfigure(1, weight=1)

        notebook = ttk.Notebook(main)
        notebook.pack(fill="both", expand=True)

        self.index_text_widget = self._create_text_tab(notebook, "Chỉ mục")
        self.result_text = self._create_text_tab(notebook, "Kết quả")
        self.help_text = self._create_text_tab(notebook, "Hướng dẫn")

        self.help_text.insert(
            "1.0",
            "1. Chọn thư mục chứa doc1.txt, doc2.txt, ..., stoplist.txt, query.txt\n"
            "2. Nhấn 'Tạo chỉ mục'\n"
            "3. Tìm 'chuông' -> hệ thống ưu tiên khớp đúng 'chuông' trước\n"
            "4. Tìm 'chuong' -> hệ thống sẽ khớp theo dạng không dấu\n"
            "5. File query: mỗi dòng chỉ có 1 từ\n"
        )
        self.help_text.config(state="disabled")

        self.status_var = tk.StringVar(value="Sẵn sàng.")
        ttk.Label(main, textvariable=self.status_var).pack(anchor="w", pady=(8, 0))

    def _create_text_tab(self, notebook: ttk.Notebook, title: str) -> tk.Text:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=title)

        text = tk.Text(frame, wrap="word", font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)

        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return text

    def choose_directory(self) -> None:
        folder = filedialog.askdirectory(title="Chọn thư mục dữ liệu")
        if folder:
            self.directory_var.set(folder)
            candidate = os.path.join(folder, "query.txt")
            if os.path.exists(candidate):
                self.queryfile_var.set(candidate)

    def choose_queryfile(self) -> None:
        filepath = filedialog.askopenfilename(
            title="Chọn file query",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if filepath:
            self.queryfile_var.set(filepath)

    def _get_top_n(self) -> int:
        try:
            n = int(self.topn_var.get().strip())
            if n <= 0:
                raise ValueError
            return n
        except Exception as exc:
            raise ValueError("Top N phải là số nguyên dương.") from exc

    def create_index(self) -> None:
        try:
            directory = self.directory_var.get().strip()
            stoplist = self.stoplist_var.get().strip()
            if not directory:
                raise ValueError("Bạn chưa chọn thư mục dữ liệu.")
            if not stoplist:
                raise ValueError("Bạn chưa nhập tên file stoplist.")

            self.index.create_index(directory, stoplist)
            self.index_text_widget.delete("1.0", "end")
            self.index_text_widget.insert("1.0", self.index.index_text())

            self.result_text.delete("1.0", "end")
            self.result_text.insert("1.0", "Đã tạo chỉ mục thành công. Bạn có thể truy vấn.")
            self.status_var.set("Đã tạo chỉ mục.")
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))
            self.status_var.set("Tạo chỉ mục thất bại.")

    def search_word(self) -> None:
        try:
            if not self.index.doc_table:
                raise ValueError("Bạn cần tạo chỉ mục trước.")
            word = self.word_var.get().strip()
            if not word:
                raise ValueError("Bạn chưa nhập từ truy vấn.")

            n = self._get_top_n()
            results = self.index.find_word(word, n)

            self.result_text.delete("1.0", "end")
            self.result_text.insert("end", f"===== Find(Word='{word}', N={n}) =====\n")
            if not results:
                self.result_text.insert("end", "Không tìm thấy tài liệu phù hợp.\n")
            else:
                for rank, (doc_id, filename, score, match_type) in enumerate(results, start=1):
                    self.result_text.insert(
                        "end",
                        f"{rank}. doc_id={doc_id}, file={filename}, freq={score}, match={match_type}\n"
                    )

            self.status_var.set("Đã truy vấn 1 từ.")
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))
            self.status_var.set("Truy vấn thất bại.")

    def search_wordfile(self) -> None:
        try:
            if not self.index.doc_table:
                raise ValueError("Bạn cần tạo chỉ mục trước.")
            queryfile = self.queryfile_var.get().strip()
            if not queryfile:
                raise ValueError("Bạn chưa chọn file query.")

            n = self._get_top_n()
            results = self.index.find_wordfile(queryfile, n)

            self.result_text.delete("1.0", "end")
            self.result_text.insert("end", f"===== Find(WordFile='{queryfile}', N={n}) =====\n")
            if not results:
                self.result_text.insert("end", "Không tìm thấy tài liệu phù hợp.\n")
            else:
                for rank, (doc_id, filename, total_freq) in enumerate(results, start=1):
                    self.result_text.insert(
                        "end",
                        f"{rank}. doc_id={doc_id}, file={filename}, total_freq={total_freq}\n"
                    )

            self.status_var.set("Đã truy vấn bằng file.")
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))
            self.status_var.set("Truy vấn thất bại.")


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
