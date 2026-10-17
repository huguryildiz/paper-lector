# LitSearch example: papers

Question (LitSearch, inline_acl, quality 2, specificity 0):

> Which studies should I look into that have explored the task of factuality in abstractive summarization and proposed ways to detect hallucinated content in generated text?

Source: [LitSearch](https://huggingface.co/datasets/princeton-nlp/LitSearch) (Ajith et al., 2024), `query/full-00000-of-00001.parquet`. Its 5 gold papers were resolved from their Semantic Scholar corpus ids. `nie2019` is not on arXiv and comes from the ACL Anthology.

The 35 distractors are the first 5 arXiv API relevance results (2018 to 2021, gold papers excluded) for seven nearby queries listed in the `group` column. LitSearch only marks the gold papers. Some distractors still touch the question, for example `raunak2021` and `wang2020` on hallucination in translation, so a distractor ranked high is not always a ranking error.

| file | role | group | first author | year | title | arXiv | DOI |
| --- | --- | --- | --- | --- | --- | --- | --- |
| maynez2020_2005-00661 | gold | LitSearch gold | Joshua Maynez | 2020 | On Faithfulness and Factuality in Abstractive Summarization | 2005.00661 | 10.18653/v1/2020.acl-main.173 |
| zhou2020_2011-02593 | gold | LitSearch gold | Chunting Zhou | 2020 | Detecting Hallucinated Content in Conditional Neural Sequence Generation | 2011.02593 | 10.18653/v1/2021.findings-acl.120 |
| nie2019_P19-1256 | gold | LitSearch gold | Feng Nie | 2019 | A Simple Recipe towards Reducing Hallucination in Neural Surface Realisation |  | 10.18653/v1/P19-1256 |
| pagnoni2021_2104-13346 | gold | LitSearch gold | Artidoro Pagnoni | 2021 | Understanding Factuality in Abstractive Summarization with FRANK: A Benchmark for Factuality Metrics | 2104.13346 | 10.18653/V1/2021.NAACL-MAIN.383 |
| kryscinski2019_1910-12840 | gold | LitSearch gold | Wojciech Kryscinski | 2019 | Evaluating the Factual Consistency of Abstractive Text Summarization | 1910.12840 | 10.18653/v1/2020.emnlp-main.750 |
| ma2018_1805-01089 | distractor | summarization | Shuming Ma | 2018 | A Hierarchical End-to-End Model for Jointly Improving Text Summarization and Sentiment Classification | 1805.01089 | 10.48550/arXiv.1805.01089 |
| jachim2021_2104-00782 | distractor | summarization | Peter Jachim | 2021 | "TL;DR:" Out-of-Context Adversarial Text Summarization and Hashtag Recommendation | 2104.00782 | 10.48550/arXiv.2104.00782 |
| moradi2019_1903-02861 | distractor | summarization | Milad Moradi | 2019 | Small-world networks for summarization of biomedical articles | 1903.02861 | 10.48550/arXiv.1903.02861 |
| dong2018_1804-04589 | distractor | summarization | Yue Dong | 2018 | A Survey on Neural Network-Based Summarization Methods | 1804.04589 | 10.48550/arXiv.1804.04589 |
| ni2021_2108-12738 | distractor | summarization | Ansong Ni | 2021 | SummerTime: Text Summarization Toolkit for Non-experts | 2108.12738 | 10.48550/arXiv.2108.12738 |
| tevet2018_1810-12686 | distractor | text generation evaluation | Guy Tevet | 2018 | Evaluating Text GANs as Language Models | 1810.12686 | 10.48550/arXiv.1810.12686 |
| narayan2020_2004-11026 | distractor | text generation evaluation | Shashi Narayan | 2020 | QURIOUS: Question Generation Pretraining for Text Generation | 2004.11026 | 10.48550/arXiv.2004.11026 |
| zhu2018_1802-01886 | distractor | text generation evaluation | Yaoming Zhu | 2018 | Texygen: A Benchmarking Platform for Text Generation Models | 1802.01886 | 10.48550/arXiv.1802.01886 |
| khashabi2021_2101-06561 | distractor | text generation evaluation | Daniel Khashabi | 2021 | GENIE: Toward Reproducible and Standardized Human Evaluation for Text Generation | 2101.06561 | 10.48550/arXiv.2101.06561 |
| pillutla2021_2102-01454 | distractor | text generation evaluation | Krishna Pillutla | 2021 | MAUVE: Measuring the Gap Between Neural Text and Human Text using Divergence Frontiers | 2102.01454 | 10.48550/arXiv.2102.01454 |
| li2020_2008-12918 | distractor | knowledge-grounded dialogue | Linxiao Li | 2020 | Zero-Resource Knowledge-Grounded Dialogue Generation | 2008.12918 | 10.48550/arXiv.2008.12918 |
| li2021_2112-07924 | distractor | knowledge-grounded dialogue | Yu Li | 2021 | Knowledge-Grounded Dialogue Generation with a Unified Knowledge Representation | 2112.07924 | 10.48550/arXiv.2112.07924 |
| dziri2021_2105-00071 | distractor | knowledge-grounded dialogue | Nouha Dziri | 2021 | Evaluating Attribution in Dialogue Systems: The BEGIN Benchmark | 2105.00071 | 10.48550/arXiv.2105.00071 |
| zhao2020_2002-10348 | distractor | knowledge-grounded dialogue | Xueliang Zhao | 2020 | Low-Resource Knowledge-Grounded Dialogue Generation | 2002.10348 | 10.48550/arXiv.2002.10348 |
| bao2021_2105-02482 | distractor | knowledge-grounded dialogue | Siqi Bao | 2021 | A Unified Pre-training Framework for Conversational AI | 2105.02482 | 10.48550/arXiv.2105.02482 |
| raunak2021_2104-06683 | distractor | hallucination in machine translation | Vikas Raunak | 2021 | The Curious Case of Hallucinations in Neural Machine Translation | 2104.06683 | 10.48550/arXiv.2104.06683 |
| wang2020_2005-03642 | distractor | hallucination in machine translation | Chaojun Wang | 2020 | On Exposure Bias, Hallucination and Domain Shift in Neural Machine Translation | 2005.03642 | 10.48550/arXiv.2005.03642 |
| muller2019_1911-03109 | distractor | hallucination in machine translation | Mathias Müller | 2019 | Domain Robustness in Neural Machine Translation | 1911.03109 | 10.48550/arXiv.1911.03109 |
| bogoychev2021_2101-00421 | distractor | hallucination in machine translation | Nikolay Bogoychev | 2021 | The Highs and Lows of Simple Lexical Domain Adaptation Approaches for Neural Machine Translation | 2101.00421 | 10.48550/arXiv.2101.00421 |
| miao2021_2105-11098 | distractor | hallucination in machine translation | Mengqi Miao | 2021 | Prevent the Language Model from being Overconfident in Neural Machine Translation | 2105.11098 | 10.48550/arXiv.2105.11098 |
| kale2020_2005-10433 | distractor | data-to-text generation | Mihir Kale | 2020 | Text-to-Text Pre-Training for Data-to-Text Tasks | 2005.10433 | 10.48550/arXiv.2005.10433 |
| kasner2020_2011-01694 | distractor | data-to-text generation | Zdeněk Kasner | 2020 | Data-to-Text Generation with Iterative Text Editing | 2011.01694 | 10.48550/arXiv.2011.01694 |
| ma2021_2110-08417 | distractor | data-to-text generation | Kaixin Ma | 2021 | Open Domain Question Answering with A Unified Knowledge Interface | 2110.08417 | 10.48550/arXiv.2110.08417 |
| ferreira2019_1908-09022 | distractor | data-to-text generation | Thiago Castro Ferreira | 2019 | Neural data-to-text generation: A comparison between pipeline and end-to-end architectures | 1908.09022 | 10.48550/arXiv.1908.09022 |
| pauws2018_1808-03507 | distractor | data-to-text generation | Steffen Pauws | 2018 | Making effective use of healthcare data using data-to-text technology | 1808.03507 | 10.48550/arXiv.1808.03507 |
| kamath2019_1911-00712 | distractor | reading comprehension | Sanjay Kamath | 2019 | How to Pre-Train Your Model? Comparison of Different Pre-Training Models for Biomedical Question Answering | 1911.00712 | 10.48550/arXiv.1911.00712 |
| mozannar2019_1906-05394 | distractor | reading comprehension | Hussein Mozannar | 2019 | Neural Arabic Question Answering | 1906.05394 | 10.48550/arXiv.1906.05394 |
| malmaud2020_2009-14780 | distractor | reading comprehension | Jonathan Malmaud | 2020 | Bridging Information-Seeking Human Gaze and Machine Reading Comprehension | 2009.14780 | 10.48550/arXiv.2009.14780 |
| yu2021_2102-01226 | distractor | reading comprehension | Dian Yu | 2021 | Self-Teaching Machines to Read and Comprehend with Large-Scale Multi-Subject Question-Answering Data | 2102.01226 | 10.48550/arXiv.2102.01226 |
| heinrich2021_2109-13209 | distractor | reading comprehension | Quentin Heinrich | 2021 | FQuAD2.0: French Question Answering and knowing that you know nothing | 2109.13209 | 10.48550/arXiv.2109.13209 |
| liu2019_1910-09796 | distractor | fact verification | Zhenghao Liu | 2019 | Fine-grained Fact Verification with Kernel Graph Attention Network | 1910.09796 | 10.48550/arXiv.1910.09796 |
| li2020_2010-05202 | distractor | fact verification | Qifei Li | 2020 | Connecting the Dots Between Fact Verification and Fake News Detection | 2010.05202 | 10.48550/arXiv.2010.05202 |
| yang2021_2109-11020 | distractor | fact verification | Xiaoyu Yang | 2021 | Exploring Decomposition for Table-based Fact Verification | 2109.11020 | 10.48550/arXiv.2109.11020 |
| pan2021_2105-14682 | distractor | fact verification | Liangming Pan | 2021 | Zero-shot Fact Verification by Claim Generation | 2105.14682 | 10.48550/arXiv.2105.14682 |
| roberts2020_2012-08919 | distractor | fact verification | Denisa A. O. Roberts | 2020 | Multilingual Evidence Retrieval and Fact Verification to Combat Global Disinformation: The Power of Polyglotism | 2012.08919 | 10.48550/arXiv.2012.08919 |

## Reproduce

```
cd examples/litsearch
# download the 40 PDFs listed above into pdfs/ (arXiv ids, nie2019 from the ACL Anthology)
python ../../scripts/rank.py --out runs/<new-name> --expect maynez2020_2005-00661,zhou2020_2011-02593,nie2019_P19-1256,pagnoni2021_2104-13346,kryscinski2019_1910-12840
python make_svg.py runs/<new-name>_hybrid.csv ../../assets/example-output.svg
```

`runs/litsearch_hybrid.csv` and `runs/litsearch_run.json` are the run behind the README image.
