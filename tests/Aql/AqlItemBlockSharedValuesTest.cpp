////////////////////////////////////////////////////////////////////////////////
/// DISCLAIMER
///
/// Copyright 2014-2024 ArangoDB GmbH, Cologne, Germany
/// Copyright 2004-2014 triAGENS GmbH, Cologne, Germany
///
/// Licensed under the Business Source License 1.1 (the "License");
/// you may not use this file except in compliance with the License.
/// You may obtain a copy of the License at
///
///     https://github.com/arangodb/arangodb/blob/devel/LICENSE
///
/// Unless required by applicable law or agreed to in writing, software
/// distributed under the License is distributed on an "AS IS" BASIS,
/// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
/// See the License for the specific language governing permissions and
/// limitations under the License.
///
/// Copyright holder is ArangoDB GmbH, Cologne, Germany
///
/// @author Comprehensive tests for AqlItemBlock with shared AqlValues
///
/// PURPOSE:
/// --------
/// This test file contains comprehensive tests for AqlItemBlock when multiple
/// AqlValues point to the same underlying data. This tests reference counting,
/// memory management, and proper cleanup in various scenarios:
///
/// 1. Multiple managed slices pointing to the same data
/// 2. Multiple supervised slices pointing to the same data
/// 3. Mixed managed and supervised slices pointing to the same data
/// 4. Reference counting behavior with setValue() and referenceValuesFromRow()
/// 5. Proper cleanup when blocks are destroyed
///
////////////////////////////////////////////////////////////////////////////////

#include "gtest/gtest.h"

#include "Aql/AqlItemBlock.h"
#include "Aql/AqlItemBlockManager.h"
#include "Aql/AqlValue.h"
#include "Aql/RegIdFlatSet.h"
#include "Aql/SharedAqlItemBlockPtr.h"
#include "Basics/GlobalResourceMonitor.h"
#include "Basics/ResourceUsage.h"
#include "Basics/VelocyPackHelper.h"

#include <boost/container/flat_set.hpp>
#include <velocypack/Builder.h>
#include <velocypack/Slice.h>
#include <velocypack/Value.h>

using namespace arangodb;
using namespace arangodb::aql;
using namespace arangodb::basics;

namespace arangodb {
namespace tests {
namespace aql {

class AqlItemBlockSharedValuesTest : public ::testing::Test {
 protected:
  arangodb::GlobalResourceMonitor global{};
  arangodb::ResourceMonitor monitor{global};
  AqlItemBlockManager itemBlockManager{monitor};

  // Helper to create a managed slice AqlValue (no ResourceMonitor)
  AqlValue createManagedSlice(std::string const& content) {
    arangodb::velocypack::Builder b;
    b.add(arangodb::velocypack::Value(content));
    // Create managed slice by not passing ResourceMonitor*
    return AqlValue(b.slice(), static_cast<arangodb::velocypack::ValueLength>(
                                   b.slice().byteSize()));
  }

  // Helper to create a supervised slice AqlValue (with ResourceMonitor)
  AqlValue createSupervisedSlice(std::string const& content) {
    arangodb::velocypack::Builder b;
    b.add(arangodb::velocypack::Value(content));
    return AqlValue(
        b.slice(),
        static_cast<arangodb::velocypack::ValueLength>(b.slice().byteSize()),
        &monitor);
  }

  // Helper to create a large managed slice (to ensure it's not inlined)
  AqlValue createLargeManagedSlice(size_t size = 200) {
    std::string content(size, 'x');
    return createManagedSlice(content);
  }

  // Helper to create a large supervised slice (to ensure it's not inlined)
  AqlValue createLargeSupervisedSlice(size_t size = 200) {
    std::string content(size, 'x');
    return createSupervisedSlice(content);
  }
};

// ============================================================================
// TEST SUITE 1: Multiple Managed Slices Pointing to Same Data
// ============================================================================

TEST_F(AqlItemBlockSharedValuesTest, MultipleManagedSlicesSameData_SetValue) {
  auto block = itemBlockManager.requestBlock(3, 1);

  // Create a managed slice
  AqlValue managed = createLargeManagedSlice(200);
  ASSERT_EQ(managed.type(), AqlValue::VPACK_MANAGED_SLICE);
  ASSERT_TRUE(managed.requiresDestruction());

  size_t expectedMemory = managed.memoryUsage();
  size_t initialMemory = monitor.current();

  // Set the same value in multiple rows
  // Each setValue() should increment the refCount in _valueCount
  block->setValue(0, 0, managed);
  block->setValue(1, 0, managed);
  block->setValue(2, 0, managed);

  // Memory should be accounted once (all three point to same data)
  // For managed slices, memory is tracked by the block via ResourceMonitor
  // when refCount == 1 in setValue()
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);

  // Verify all rows point to the same data
  AqlValue const& val0 = block->getValueReference(0, 0);
  AqlValue const& val1 = block->getValueReference(1, 0);
  AqlValue const& val2 = block->getValueReference(2, 0);
  EXPECT_EQ(val0.data(), val1.data())
      << "Row 0 and 1 should point to same memory";
  EXPECT_EQ(val1.data(), val2.data())
      << "Row 1 and 2 should point to same memory";
  EXPECT_EQ(val0.type(), AqlValue::VPACK_MANAGED_SLICE);

  // Destroy the block - should properly clean up
  block.reset(nullptr);

  // All memory should be released
  EXPECT_EQ(monitor.current(), 0U);
}

TEST_F(AqlItemBlockSharedValuesTest,
       MultipleManagedSlicesSameData_ReferenceValuesFromRow) {
  auto block = itemBlockManager.requestBlock(3, 1);

  // Create a managed slice
  AqlValue managed = createLargeManagedSlice(200);
  ASSERT_EQ(managed.type(), AqlValue::VPACK_MANAGED_SLICE);

  size_t expectedMemory = managed.memoryUsage();
  size_t initialMemory = monitor.current();

  // Set value in row 0
  block->setValue(0, 0, managed);
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);

  // Reference it to row 1 and row 2
  RegIdFlatSet regs;
  regs.insert(RegisterId::makeRegular(0));
  block->referenceValuesFromRow(1, regs, 0);
  block->referenceValuesFromRow(2, regs, 0);

  // Memory should still be the same (same data, just more references)
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);

  // Verify all rows point to the same data
  AqlValue const& val0 = block->getValueReference(0, 0);
  AqlValue const& val1 = block->getValueReference(1, 0);
  AqlValue const& val2 = block->getValueReference(2, 0);
  EXPECT_EQ(val0.data(), val1.data());
  EXPECT_EQ(val1.data(), val2.data());

  // Destroy the block
  block.reset(nullptr);

  // All memory should be released
  EXPECT_EQ(monitor.current(), 0U);
}

TEST_F(AqlItemBlockSharedValuesTest,
       MultipleManagedSlicesSameData_DestroyValue) {
  auto block = itemBlockManager.requestBlock(3, 1);

  // Create a managed slice
  AqlValue managed = createLargeManagedSlice(200);
  ASSERT_EQ(managed.type(), AqlValue::VPACK_MANAGED_SLICE);

  size_t expectedMemory = managed.memoryUsage();
  size_t initialMemory = monitor.current();

  // Set value in all three rows
  block->setValue(0, 0, managed);
  block->setValue(1, 0, managed);
  block->setValue(2, 0, managed);
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);

  // Destroy value in row 0 - should decrement refCount but not free memory
  block->destroyValue(0, 0);
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory)
      << "Memory should still be allocated";

  // Row 0 should be empty
  EXPECT_TRUE(block->getValueReference(0, 0).isEmpty());

  // Rows 1 and 2 should still have the value
  EXPECT_FALSE(block->getValueReference(1, 0).isEmpty());
  EXPECT_FALSE(block->getValueReference(2, 0).isEmpty());
  EXPECT_EQ(block->getValueReference(1, 0).data(),
            block->getValueReference(2, 0).data());

  // Destroy value in row 1
  block->destroyValue(1, 0);
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory)
      << "Memory should still be allocated";

  // Destroy value in row 2 - should now free memory
  block->destroyValue(2, 0);
  // Memory should be freed (allow some tolerance for overhead)
  EXPECT_LE(monitor.current(), initialMemory + 100U)
      << "Memory should be freed after last reference is destroyed";

  // Destroy the block
  block.reset(nullptr);
  // Allow some tolerance for any remaining overhead
  EXPECT_LE(monitor.current(), 100U);
}

// ============================================================================
// TEST SUITE 2: Multiple Supervised Slices Pointing to Same Data
// ============================================================================

TEST_F(AqlItemBlockSharedValuesTest,
       MultipleSupervisedSlicesSameData_SetValue) {
  auto block = itemBlockManager.requestBlock(3, 1);

  // Create a supervised slice
  AqlValue supervised = createLargeSupervisedSlice(200);
  ASSERT_EQ(supervised.type(), AqlValue::VPACK_SUPERVISED_SLICE);
  ASSERT_TRUE(supervised.requiresDestruction());

  size_t expectedMemory = supervised.memoryUsage();
  size_t initialMemory = monitor.current();

  // Set the same value in multiple rows
  block->setValue(0, 0, supervised);
  block->setValue(1, 0, supervised);
  block->setValue(2, 0, supervised);

  // For supervised slices, memory is already accounted in ResourceMonitor
  // during allocation, so we shouldn't double-count it
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);

  // Verify all rows point to the same data
  AqlValue const& val0 = block->getValueReference(0, 0);
  AqlValue const& val1 = block->getValueReference(1, 0);
  AqlValue const& val2 = block->getValueReference(2, 0);
  EXPECT_EQ(val0.data(), val1.data())
      << "Row 0 and 1 should point to same memory";
  EXPECT_EQ(val1.data(), val2.data())
      << "Row 1 and 2 should point to same memory";
  EXPECT_EQ(val0.type(), AqlValue::VPACK_SUPERVISED_SLICE);

  // Destroy the block
  block.reset(nullptr);

  // All memory should be released
  EXPECT_EQ(monitor.current(), 0U);
}

TEST_F(AqlItemBlockSharedValuesTest,
       MultipleSupervisedSlicesSameData_ReferenceValuesFromRow) {
  auto block = itemBlockManager.requestBlock(3, 1);

  // Create a supervised slice
  AqlValue supervised = createLargeSupervisedSlice(200);
  ASSERT_EQ(supervised.type(), AqlValue::VPACK_SUPERVISED_SLICE);

  size_t expectedMemory = supervised.memoryUsage();
  size_t initialMemory = monitor.current();

  // Set value in row 0
  block->setValue(0, 0, supervised);
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);

  // Reference it to row 1 and row 2
  RegIdFlatSet regs;
  regs.insert(RegisterId::makeRegular(0));
  block->referenceValuesFromRow(1, regs, 0);
  block->referenceValuesFromRow(2, regs, 0);

  // Memory should still be the same (same data, just more references)
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);

  // Verify all rows point to the same data
  AqlValue const& val0 = block->getValueReference(0, 0);
  AqlValue const& val1 = block->getValueReference(1, 0);
  AqlValue const& val2 = block->getValueReference(2, 0);
  EXPECT_EQ(val0.data(), val1.data());
  EXPECT_EQ(val1.data(), val2.data());

  // Destroy the block
  block.reset(nullptr);

  // All memory should be released
  EXPECT_EQ(monitor.current(), 0U);
}

TEST_F(AqlItemBlockSharedValuesTest,
       MultipleSupervisedSlicesSameData_DestroyValue) {
  auto block = itemBlockManager.requestBlock(3, 1);

  // Create a supervised slice
  AqlValue supervised = createLargeSupervisedSlice(200);
  ASSERT_EQ(supervised.type(), AqlValue::VPACK_SUPERVISED_SLICE);

  size_t expectedMemory = supervised.memoryUsage();
  size_t initialMemory = monitor.current();

  // Set value in all three rows
  block->setValue(0, 0, supervised);
  block->setValue(1, 0, supervised);
  block->setValue(2, 0, supervised);
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);

  // Destroy value in row 0 - should decrement refCount but not free memory
  block->destroyValue(0, 0);
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory)
      << "Memory should still be allocated";

  // Row 0 should be empty
  EXPECT_TRUE(block->getValueReference(0, 0).isEmpty());

  // Rows 1 and 2 should still have the value
  EXPECT_FALSE(block->getValueReference(1, 0).isEmpty());
  EXPECT_FALSE(block->getValueReference(2, 0).isEmpty());
  EXPECT_EQ(block->getValueReference(1, 0).data(),
            block->getValueReference(2, 0).data());

  // Destroy value in row 1
  block->destroyValue(1, 0);
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory)
      << "Memory should still be allocated";

  // Destroy value in row 2 - should now free memory
  block->destroyValue(2, 0);
  // Memory should be freed (allow some tolerance for overhead)
  EXPECT_LE(monitor.current(), initialMemory + 100U)
      << "Memory should be freed after last reference is destroyed";

  // Destroy the block
  block.reset(nullptr);
  // Allow some tolerance for any remaining overhead
  EXPECT_LE(monitor.current(), 100U);
}

// ============================================================================
// TEST SUITE 3: Mixed Managed and Supervised Slices Pointing to Same Data
// ============================================================================

TEST_F(AqlItemBlockSharedValuesTest,
       MixedManagedAndSupervisedSlices_SameContent) {
  auto block = itemBlockManager.requestBlock(4, 1);

  // Create both managed and supervised slices with the same content
  std::string content =
      "This is a test string that is long enough to not be inlined";
  AqlValue managed = createManagedSlice(content);
  AqlValue supervised = createSupervisedSlice(content);

  ASSERT_EQ(managed.type(), AqlValue::VPACK_MANAGED_SLICE);
  ASSERT_EQ(supervised.type(), AqlValue::VPACK_SUPERVISED_SLICE);

  size_t managedMemory = managed.memoryUsage();
  size_t supervisedMemory = supervised.memoryUsage();
  size_t initialMemory = monitor.current();

  // Set managed slice in rows 0 and 1
  block->setValue(0, 0, managed);
  block->setValue(1, 0, managed);

  // Set supervised slice in rows 2 and 3
  block->setValue(2, 0, supervised);
  block->setValue(3, 0, supervised);

  // Memory should account for both managed and supervised slices
  // Both types are tracked via ResourceMonitor when setValue() is called
  // (managed slices are tracked by the block, supervised slices are already
  // tracked when created, but setValue() also tracks them for block accounting)
  size_t expectedMemory = managedMemory + supervisedMemory;
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);

  // Verify managed slices point to same data
  EXPECT_EQ(block->getValueReference(0, 0).data(),
            block->getValueReference(1, 0).data());
  EXPECT_EQ(block->getValueReference(0, 0).type(),
            AqlValue::VPACK_MANAGED_SLICE);

  // Verify supervised slices point to same data
  EXPECT_EQ(block->getValueReference(2, 0).data(),
            block->getValueReference(3, 0).data());
  EXPECT_EQ(block->getValueReference(2, 0).type(),
            AqlValue::VPACK_SUPERVISED_SLICE);

  // Note: Managed and supervised slices with same content have different
  // pointers because they are separate allocations, even though content is the
  // same
  EXPECT_NE(block->getValueReference(0, 0).data(),
            block->getValueReference(2, 0).data());

  // Destroy the block
  block.reset(nullptr);

  // All memory should be released
  EXPECT_EQ(monitor.current(), 0U);
}

TEST_F(AqlItemBlockSharedValuesTest,
       MixedManagedAndSupervisedSlices_ReferenceValuesFromRow) {
  auto block = itemBlockManager.requestBlock(4, 1);

  // Create both managed and supervised slices
  std::string content1 = "First managed slice content";
  std::string content2 = "Second supervised slice content";
  AqlValue managed = createManagedSlice(content1);
  AqlValue supervised = createSupervisedSlice(content2);

  size_t managedMemory = managed.memoryUsage();
  size_t supervisedMemory = supervised.memoryUsage();
  size_t initialMemory = monitor.current();

  // Set managed slice in row 0
  block->setValue(0, 0, managed);
  // Set supervised slice in row 2
  block->setValue(2, 0, supervised);

  // Reference managed slice to row 1
  RegIdFlatSet regs;
  regs.insert(RegisterId::makeRegular(0));
  block->referenceValuesFromRow(1, regs, 0);

  // Reference supervised slice to row 3
  block->referenceValuesFromRow(3, regs, 2);

  // Memory should account for both
  size_t expectedMemory = managedMemory + supervisedMemory;
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);

  // Verify references
  EXPECT_EQ(block->getValueReference(0, 0).data(),
            block->getValueReference(1, 0).data());
  EXPECT_EQ(block->getValueReference(2, 0).data(),
            block->getValueReference(3, 0).data());

  // Destroy the block
  block.reset(nullptr);

  // All memory should be released
  EXPECT_EQ(monitor.current(), 0U);
}

// ============================================================================
// TEST SUITE 4: Complex Scenarios with Multiple Registers
// ============================================================================

TEST_F(AqlItemBlockSharedValuesTest, MultipleRegisters_AllManagedSlices) {
  auto block = itemBlockManager.requestBlock(2, 3);

  // Create managed slices
  AqlValue val1 = createLargeManagedSlice(200);
  AqlValue val2 = createLargeManagedSlice(200);
  AqlValue val3 = createLargeManagedSlice(200);

  size_t initialMemory = monitor.current();
  size_t totalMemory =
      val1.memoryUsage() + val2.memoryUsage() + val3.memoryUsage();

  // Set values in row 0
  block->setValue(0, 0, val1);
  block->setValue(0, 1, val2);
  block->setValue(0, 2, val3);

  // Reference all values to row 1
  RegIdFlatSet regs;
  regs.insert(RegisterId::makeRegular(0));
  regs.insert(RegisterId::makeRegular(1));
  regs.insert(RegisterId::makeRegular(2));
  block->referenceValuesFromRow(1, regs, 0);

  // Memory should account for all three values (each only once)
  EXPECT_EQ(monitor.current(), initialMemory + totalMemory);

  // Verify all registers in row 1 point to same data as row 0
  EXPECT_EQ(block->getValueReference(0, 0).data(),
            block->getValueReference(1, 0).data());
  EXPECT_EQ(block->getValueReference(0, 1).data(),
            block->getValueReference(1, 1).data());
  EXPECT_EQ(block->getValueReference(0, 2).data(),
            block->getValueReference(1, 2).data());

  // Destroy the block
  block.reset(nullptr);

  // All memory should be released
  EXPECT_EQ(monitor.current(), 0U);
}

TEST_F(AqlItemBlockSharedValuesTest, MultipleRegisters_AllSupervisedSlices) {
  auto block = itemBlockManager.requestBlock(2, 3);

  // Create supervised slices
  AqlValue val1 = createLargeSupervisedSlice(200);
  AqlValue val2 = createLargeSupervisedSlice(200);
  AqlValue val3 = createLargeSupervisedSlice(200);

  size_t initialMemory = monitor.current();
  size_t totalMemory =
      val1.memoryUsage() + val2.memoryUsage() + val3.memoryUsage();

  // Set values in row 0
  block->setValue(0, 0, val1);
  block->setValue(0, 1, val2);
  block->setValue(0, 2, val3);

  // Reference all values to row 1
  RegIdFlatSet regs;
  regs.insert(RegisterId::makeRegular(0));
  regs.insert(RegisterId::makeRegular(1));
  regs.insert(RegisterId::makeRegular(2));
  block->referenceValuesFromRow(1, regs, 0);

  // Memory should account for all three values
  EXPECT_EQ(monitor.current(), initialMemory + totalMemory);

  // Verify all registers in row 1 point to same data as row 0
  EXPECT_EQ(block->getValueReference(0, 0).data(),
            block->getValueReference(1, 0).data());
  EXPECT_EQ(block->getValueReference(0, 1).data(),
            block->getValueReference(1, 1).data());
  EXPECT_EQ(block->getValueReference(0, 2).data(),
            block->getValueReference(1, 2).data());

  // Destroy the block
  block.reset(nullptr);

  // All memory should be released
  EXPECT_EQ(monitor.current(), 0U);
}

TEST_F(AqlItemBlockSharedValuesTest,
       MultipleRegisters_MixedManagedAndSupervised) {
  auto block = itemBlockManager.requestBlock(2, 3);

  // Create mixed slices
  AqlValue managed1 = createLargeManagedSlice(200);
  AqlValue supervised1 = createLargeSupervisedSlice(200);
  AqlValue managed2 = createLargeManagedSlice(200);

  size_t initialMemory = monitor.current();
  size_t totalMemory = managed1.memoryUsage() + supervised1.memoryUsage() +
                       managed2.memoryUsage();

  // Set values in row 0: managed, supervised, managed
  block->setValue(0, 0, managed1);
  block->setValue(0, 1, supervised1);
  block->setValue(0, 2, managed2);

  // Reference all values to row 1
  RegIdFlatSet regs;
  regs.insert(RegisterId::makeRegular(0));
  regs.insert(RegisterId::makeRegular(1));
  regs.insert(RegisterId::makeRegular(2));
  block->referenceValuesFromRow(1, regs, 0);

  // Memory should account for all three values
  EXPECT_EQ(monitor.current(), initialMemory + totalMemory);

  // Verify references
  EXPECT_EQ(block->getValueReference(0, 0).data(),
            block->getValueReference(1, 0).data());
  EXPECT_EQ(block->getValueReference(0, 1).data(),
            block->getValueReference(1, 1).data());
  EXPECT_EQ(block->getValueReference(0, 2).data(),
            block->getValueReference(1, 2).data());

  // Verify types
  EXPECT_EQ(block->getValueReference(0, 0).type(),
            AqlValue::VPACK_MANAGED_SLICE);
  EXPECT_EQ(block->getValueReference(0, 1).type(),
            AqlValue::VPACK_SUPERVISED_SLICE);
  EXPECT_EQ(block->getValueReference(0, 2).type(),
            AqlValue::VPACK_MANAGED_SLICE);

  // Destroy the block
  block.reset(nullptr);

  // All memory should be released
  EXPECT_EQ(monitor.current(), 0U);
}

// ============================================================================
// TEST SUITE 5: Edge Cases and Stress Tests
// ============================================================================

TEST_F(AqlItemBlockSharedValuesTest, ManyRows_AllManagedSlices) {
  const size_t numRows = 10;
  auto block = itemBlockManager.requestBlock(numRows, 1);

  // Create a managed slice
  AqlValue managed = createLargeManagedSlice(200);
  size_t expectedMemory = managed.memoryUsage();
  size_t initialMemory = monitor.current();

  // Set the same value in all rows
  for (size_t i = 0; i < numRows; ++i) {
    block->setValue(i, 0, managed);
  }

  // Memory should be accounted once (all rows point to same data)
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);

  // Verify all rows point to the same data
  void const* firstData = block->getValueReference(0, 0).data();
  for (size_t i = 1; i < numRows; ++i) {
    EXPECT_EQ(block->getValueReference(i, 0).data(), firstData)
        << "Row " << i << " should point to same memory as row 0";
  }

  // Destroy the block
  block.reset(nullptr);

  // All memory should be released
  EXPECT_EQ(monitor.current(), 0U);
}

TEST_F(AqlItemBlockSharedValuesTest, ManyRows_AllSupervisedSlices) {
  const size_t numRows = 10;
  auto block = itemBlockManager.requestBlock(numRows, 1);

  // Create a supervised slice
  AqlValue supervised = createLargeSupervisedSlice(200);
  size_t expectedMemory = supervised.memoryUsage();
  size_t initialMemory = monitor.current();

  // Set the same value in all rows
  for (size_t i = 0; i < numRows; ++i) {
    block->setValue(i, 0, supervised);
  }

  // Memory should be accounted once
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);

  // Verify all rows point to the same data
  void const* firstData = block->getValueReference(0, 0).data();
  for (size_t i = 1; i < numRows; ++i) {
    EXPECT_EQ(block->getValueReference(i, 0).data(), firstData)
        << "Row " << i << " should point to same memory as row 0";
  }

  // Destroy the block
  block.reset(nullptr);

  // All memory should be released
  EXPECT_EQ(monitor.current(), 0U);
}

TEST_F(AqlItemBlockSharedValuesTest, PartialDestroy_ManagedSlices) {
  auto block = itemBlockManager.requestBlock(5, 1);

  // Create a managed slice
  AqlValue managed = createLargeManagedSlice(200);
  size_t expectedMemory = managed.memoryUsage();
  size_t initialMemory = monitor.current();

  // Set value in all rows
  for (size_t i = 0; i < 5; ++i) {
    block->setValue(i, 0, managed);
  }
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);

  // Destroy values in rows 0, 1, 2
  for (size_t i = 0; i < 3; ++i) {
    block->destroyValue(i, 0);
    EXPECT_TRUE(block->getValueReference(i, 0).isEmpty());
    // Memory should still be allocated (rows 3 and 4 still reference it)
    EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);
  }

  // Rows 3 and 4 should still have the value
  EXPECT_FALSE(block->getValueReference(3, 0).isEmpty());
  EXPECT_FALSE(block->getValueReference(4, 0).isEmpty());
  EXPECT_EQ(block->getValueReference(3, 0).data(),
            block->getValueReference(4, 0).data());

  // Destroy value in row 3
  block->destroyValue(3, 0);
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);

  // Destroy value in row 4 - should now free memory
  block->destroyValue(4, 0);
  // Memory should be freed (allow some tolerance for overhead)
  EXPECT_LE(monitor.current(), initialMemory + 100U);

  // Destroy the block
  block.reset(nullptr);
  // Allow some tolerance for any remaining overhead
  EXPECT_LE(monitor.current(), 100U);
}

TEST_F(AqlItemBlockSharedValuesTest, PartialDestroy_SupervisedSlices) {
  auto block = itemBlockManager.requestBlock(5, 1);

  // Create a supervised slice
  AqlValue supervised = createLargeSupervisedSlice(200);
  size_t expectedMemory = supervised.memoryUsage();
  size_t initialMemory = monitor.current();

  // Set value in all rows
  for (size_t i = 0; i < 5; ++i) {
    block->setValue(i, 0, supervised);
  }
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);

  // Destroy values in rows 0, 1, 2
  for (size_t i = 0; i < 3; ++i) {
    block->destroyValue(i, 0);
    EXPECT_TRUE(block->getValueReference(i, 0).isEmpty());
    // Memory should still be allocated (rows 3 and 4 still reference it)
    EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);
  }

  // Rows 3 and 4 should still have the value
  EXPECT_FALSE(block->getValueReference(3, 0).isEmpty());
  EXPECT_FALSE(block->getValueReference(4, 0).isEmpty());
  EXPECT_EQ(block->getValueReference(3, 0).data(),
            block->getValueReference(4, 0).data());

  // Destroy value in row 3
  block->destroyValue(3, 0);
  EXPECT_EQ(monitor.current(), initialMemory + expectedMemory);

  // Destroy value in row 4 - should now free memory
  block->destroyValue(4, 0);
  // Memory should be freed (allow some tolerance for overhead)
  EXPECT_LE(monitor.current(), initialMemory + 100U);

  // Destroy the block
  block.reset(nullptr);
  // Allow some tolerance for any remaining overhead
  EXPECT_LE(monitor.current(), 100U);
}

TEST_F(AqlItemBlockSharedValuesTest, StealAndDestroy_ManagedSlices) {
  auto block = itemBlockManager.requestBlock(2, 1);

  // Create a managed slice
  AqlValue managed = createLargeManagedSlice(200);
  size_t expectedMemory = managed.memoryUsage();
  size_t initialMemory = monitor.current();

  // Set value in both rows
  block->setValue(0, 0, managed);
  block->setValue(1, 0, managed);
  // Memory should increase (both rows share the same data, so only one
  // allocation)
  size_t memoryAfterSet = monitor.current();
  EXPECT_GE(memoryAfterSet, initialMemory);

  // Steal value from row 0
  AqlValue stolen = block->getValue(0, 0);
  block->steal(stolen);

  // Row 1 should still have the value
  EXPECT_FALSE(block->getValueReference(1, 0).isEmpty());
  // After stealing, block should no longer track row 0's value
  // Row 1's value is still tracked
  size_t memoryAfterSteal = monitor.current();
  EXPECT_GE(memoryAfterSteal, initialMemory);

  // Destroy the block - should clean up row 1
  // For managed slices, the stolen value's memory is not tracked by
  // ResourceMonitor (it's managed by the AqlValue itself), so memory might
  // decrease
  block.reset(nullptr);

  // Stolen value is still alive but not tracked by ResourceMonitor for managed
  // slices Allow tolerance for overhead
  size_t memoryAfterBlockDestroy = monitor.current();
  EXPECT_LE(memoryAfterBlockDestroy, initialMemory + expectedMemory + 100U);

  // Clean up stolen value
  stolen.destroy();

  // All memory should be released (allow tolerance for overhead)
  EXPECT_LE(monitor.current(), initialMemory + 100U);
}

TEST_F(AqlItemBlockSharedValuesTest, StealAndDestroy_SupervisedSlices) {
  auto block = itemBlockManager.requestBlock(2, 1);

  // Create a supervised slice
  AqlValue supervised = createLargeSupervisedSlice(200);
  size_t expectedMemory = supervised.memoryUsage();
  size_t initialMemory = monitor.current();

  // Set value in both rows
  block->setValue(0, 0, supervised);
  block->setValue(1, 0, supervised);
  // Memory should increase (both rows share the same data, so only one
  // allocation)
  size_t memoryAfterSet = monitor.current();
  EXPECT_GE(memoryAfterSet, initialMemory);

  // Steal value from row 0
  AqlValue stolen = block->getValue(0, 0);
  block->steal(stolen);

  // Row 1 should still have the value
  EXPECT_FALSE(block->getValueReference(1, 0).isEmpty());
  // After stealing, block should no longer track row 0's value
  // Row 1's value is still tracked
  size_t memoryAfterSteal = monitor.current();
  EXPECT_GE(memoryAfterSteal, initialMemory);

  // Destroy the block - should clean up row 1
  // For supervised slices, the stolen value's memory is still tracked by
  // ResourceMonitor (it was allocated with ResourceMonitor), so memory should
  // remain
  block.reset(nullptr);

  // Stolen supervised value is still alive and tracked by ResourceMonitor
  // Memory should be close to initialMemory + expectedMemory (stolen value)
  size_t memoryAfterBlockDestroy = monitor.current();
  EXPECT_GE(memoryAfterBlockDestroy, initialMemory);
  EXPECT_LE(memoryAfterBlockDestroy, initialMemory + expectedMemory + 100U);

  // Clean up stolen value
  stolen.destroy();

  // All memory should be released (allow tolerance for overhead)
  EXPECT_LE(monitor.current(), initialMemory + 100U);
}

}  // namespace aql
}  // namespace tests
}  // namespace arangodb
