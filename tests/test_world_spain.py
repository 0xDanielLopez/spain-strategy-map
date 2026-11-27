"""Pure rules of the Spain world builder: CCAA vote, county pick, cover and relief classes."""

import unittest
from collections import Counter

from pipeline.build import world


class CcaaVoteTest(unittest.TestCase):
    def test_most_samples_win(self):
        self.assertEqual(world.ccaa_vote([2, 2, 2, 5, 5, 7, 7], 7), 2)

    def test_votes_count_samples_not_municipalities(self):
        # Many municipalities of one CCAA do not matter: the caller maps each sample to its CCAA first.
        self.assertEqual(world.ccaa_vote([4, 4, 4, 1, 1, 1, 1], 4), 1)

    def test_tie_goes_to_the_centre_ccaa(self):
        self.assertEqual(world.ccaa_vote([3, 3, 3, 8, 8, 8, 5], 8), 8)

    def test_tie_without_centre_goes_to_lowest_index(self):
        self.assertEqual(world.ccaa_vote([3, 3, 3, 8, 8, 8, 5], 5), 3)
        self.assertEqual(world.ccaa_vote([3, 3, 3, 8, 8, 8, 5], None), 3)

    def test_single_ccaa(self):
        self.assertEqual(world.ccaa_vote([6], 6), 6)


class PickCountyTest(unittest.TestCase):
    # municipality index -> CCAA
    MUNI_CCAA = [0, 0, 1, 1, 1]

    def test_centre_municipality_wins_if_in_owner_ccaa(self):
        self.assertEqual(world.pick_county([1, 0, 0, 0, 3, 3, 3], self.MUNI_CCAA, 0), 1)

    def test_centre_outside_owner_ccaa_falls_back_to_most_common(self):
        self.assertEqual(world.pick_county([0, 1, 1, 3, 3, 3, 2], self.MUNI_CCAA, 1), 3)

    def test_tie_goes_to_lowest_index(self):
        self.assertEqual(world.pick_county([0, 3, 3, 2, 2, -1, -1], self.MUNI_CCAA, 1), 2)

    def test_samples_outside_every_municipality_are_ignored(self):
        self.assertEqual(world.pick_county([-1, -1, 0, -1, -1, -1, -1], self.MUNI_CCAA, 0), 0)

    def test_no_sample_in_owner_ccaa(self):
        self.assertEqual(world.pick_county([0, 1, -1, -1, -1, -1, -1], self.MUNI_CCAA, 1 + 1), -1)


class CoverAndReliefTest(unittest.TestCase):
    def test_built_up_threshold(self):
        counts = Counter({50: 2, 40: 8})
        self.assertEqual(world.dominant_cover(counts, 10), world.URBAN_ID)  # 20% >= URBAN_MIN_PCT
        self.assertEqual(world.dominant_cover(Counter({50: 1, 40: 9}), 10), 7)

    def test_groups_and_ties(self):
        self.assertEqual(world.dominant_cover(Counter({10: 5, 20: 5}), 10), 3)  # dict order: tree first
        self.assertEqual(world.dominant_cover(Counter({30: 2, 100: 2, 40: 3}), 7), 5)  # grass + moss
        self.assertEqual(world.dominant_cover(Counter({70: 4}), 4), 11)
        self.assertEqual(world.dominant_cover(Counter(), 0), 0)

    def test_table_ids(self):
        self.assertEqual([row[0] for row in world.COVER], [3, 4, 5, 7, 8, 9, 10, 11])

    def test_relief_thresholds(self):
        hi, mo = world.HILLS_STD_M, world.MOUNTAINS_STD_M
        self.assertEqual(world.classify_relief(500, hi - 1), world.FLAT)
        self.assertEqual(world.classify_relief(500, hi), world.HILLS)
        self.assertEqual(world.classify_relief(500, mo), world.MOUNTAINS)
        self.assertEqual(world.classify_relief(2800, 10), world.PEAKS)
        self.assertEqual(world.classify_relief(500, 85, hills=85), world.HILLS)
        self.assertEqual(world.classify_relief(500, 84, hills=85), world.FLAT)

    def test_forced_points_are_unique_and_named(self):
        names = [n for n, _, _ in world.FORCED_POINTS]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 13)


if __name__ == "__main__":
    unittest.main()
