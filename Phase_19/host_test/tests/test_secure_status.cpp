/**
 * @file test_secure_status.cpp
 * @brief Phase 19 G3+G4 host tests: SECURE_OK/FAIL magic + double-branch.
 *
 * Locks:
 *  - Hamming distance SECURE_OK ^ SECURE_FAIL == 0xFFFF (16-bit).
 *  - bundle_status_from_esp / _bool mapping.
 *  - secure_check_double passes on OK, fails on FAIL.
 *  - Simulated single-skip: mutating one compare still fails closed
 *    (modelled by checking that a FAIL status never passes, and that
 *    flipping one of the two reads is insufficient — the helper reads
 *    the live volatile twice, so a single skipped branch in the *caller*
 *    still leaves the second branch to halt; here we assert the helper
 *    itself is strict).
 *  - Corrupt bundle still rejected (scrub path would trigger in loader;
 *    helpers return FAIL so halt_and_scrub runs — no early return without
 *    scrub in main.c by construction, covered by review).
 */
#include "catch2/catch.hpp"

extern "C" {
#include "bundle_validate.h"
#include "loader_config.h"
#include "esp_err.h"
}

TEST_CASE("secure magic Hamming distance is 16") {
  REQUIRE((SECURE_OK ^ SECURE_FAIL) == 0xFFFF);
  // Single-bit fault cannot turn FAIL into OK.
  for (int b = 0; b < 16; b++) {
    REQUIRE(((SECURE_FAIL ^ (1u << b)) & 0xFFFFu) != SECURE_OK);
  }
}

TEST_CASE("bundle_status_from_esp maps correctly") {
  REQUIRE(bundle_status_from_esp(ESP_OK) == SECURE_OK);
  REQUIRE(bundle_status_from_esp(ESP_FAIL) == SECURE_FAIL);
  REQUIRE(bundle_status_from_esp(ESP_ERR_INVALID_SIZE) == SECURE_FAIL);
  REQUIRE(bundle_status_from_esp(ESP_ERR_INVALID_STATE) == SECURE_FAIL);
}

TEST_CASE("bundle_status_from_bool maps correctly") {
  REQUIRE(bundle_status_from_bool(1) == SECURE_OK);
  REQUIRE(bundle_status_from_bool(0) == SECURE_FAIL);
}

TEST_CASE("secure_check_double is strict") {
  volatile secure_status_t ok = SECURE_OK;
  REQUIRE(secure_check_double(&ok) == 1);

  volatile secure_status_t fail = SECURE_FAIL;
  REQUIRE(secure_check_double(&fail) == 0);

  // Zero / random values never pass.
  volatile secure_status_t zero = 0;
  REQUIRE(secure_check_double(&zero) == 0);
  volatile secure_status_t other = 0x1234;
  REQUIRE(secure_check_double(&other) == 0);
}

TEST_CASE("corrupt bundle helpers return FAIL-mapped status") {
  // Phase 14 F2 class: pl_size past fw_size must map to SECURE_FAIL.
  REQUIRE(bundle_status_from_esp(bundle_validate_main_size(101, 100)) ==
          SECURE_FAIL);
  REQUIRE(bundle_status_from_esp(bundle_validate_main_size(100, 100 +
          sizeof(bl_section_t))) == SECURE_OK);
}

TEST_CASE("canary config sanity") {
  REQUIRE(CANARY_LEN == 1024 * 1024);
  REQUIRE(CANARY_LEN % 4 == 0);
#if CONFIG_IDF_TARGET_ESP32P4
  REQUIRE(CANARY_PADDR == (uint32_t)0x48400000);
#elif CONFIG_IDF_TARGET_ESP32S3
  // Must avoid the S3 JMP zone alias 0x403A0000-0x403B8000.
  REQUIRE(CANARY_PADDR == (uint32_t)0x3C7F0000);
#endif
  REQUIRE(GLITCH_JITTER_MIN_MS == 1);
  REQUIRE(GLITCH_JITTER_MAX_MS == 5);
  REQUIRE(GLITCH_JITTER_MAX_MS >= GLITCH_JITTER_MIN_MS);
}
