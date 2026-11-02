from pipeline.grounding import unsupported, values


def test_values_across_notations():
    assert values('a 1.61 Gb genome') == [1_610_000_000]
    assert values('82 million') == [82_000_000]
    assert values('12 datasets at p<0.05') == [12, 0.05]
    assert values('1,234.5 reads') == [1234.5]


def test_values_compact_suffixes_and_hyphenated_scales():
    assert values('>17K samples') == [17_000]
    assert values('N=1M') == [1_000_000]
    assert values('Sample count: 17K.') == [17_000]
    assert values('a 1.2-billion-parameter model') == [1_200_000_000]
    assert values('2-16 bp') == [2, 16]


def test_values_notation_variants():
    assert values('macro-F1 of 0{middle dot}96') == [0.96]
    assert values('only 13·3% of labels') == [13.3]
    assert values(r'on average $\sim18-28 \times$ speedup') == [18, 28]
    assert values('TP53 and H3K27M') == []


def test_values_units_and_spelled_out_compounds():
    assert values('51.9 Mb contig') == [51_900_000]
    assert values('300 kbp region') == [300_000]
    assert values('a 1.9 gigabases genome') == [1_900_000_000]
    assert values('fifty-eight regions') == [58]
    assert values('3 T MRI') == [3]


def test_word_numbers_carry_their_scale():
    assert values('more than one million atoms') == [1_000_000]
    assert values('two hundred samples') == [200]
    assert values('three thousand cells') == [3_000]
    assert unsupported('Used for 10 years.', 'For ten years it has been used.') == []


def test_unsupported_skips_small_values_and_years():
    assert unsupported('We used 3 datasets in 2024 with 47 samples', 'twelve samples') == [47]
    assert unsupported('1899, 1900, 2100, 2101, 2024.5', '') == [1899, 2101, 2024.5]


def test_unsupported_accepts_other_notation_and_tolerance():
    assert unsupported('82M records from a 1.6 Gb assembly', '82 million records; 1.61 Gb') == []
    assert unsupported('98', '100') == []
    assert unsupported('100', '98') == []
    assert unsupported('97', '100') == [97]
    assert unsupported('98', '100', tolerance=0.01) == [98]


def test_unsupported_flags_invented_value():
    assert unsupported('They used 47 datasets.', 'We used 12 datasets.') == [47]


def test_unsupported_keeps_order_and_deduplicates():
    assert unsupported('twelve groups, 47 samples, twelve groups, 47 samples', '') == [12, 47]
    assert unsupported('3 datasets and 12 samples', '', min_value=3) == [3, 12]
