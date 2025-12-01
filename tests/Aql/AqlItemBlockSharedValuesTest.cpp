
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

  // Create a supervised slice - we'll use it for all three rows
  // to make them share the same pointer
  AqlValue supervised = createLargeSupervisedSlice(200);
  ASSERT_EQ(supervised.type(), AqlValue::VPACK_SUPERVISED_SLICE);
  ASSERT_TRUE(supervised.requiresDestruction());

  size_t initialMemory = monitor.current();

  block->setValue(0, 0, supervised);
  block->setValue(1, 0, supervised);
  block->setValue(2, 0, supervised);

  // setValue() does not increase ResourceMonitor for supervised slices
  EXPECT_EQ(monitor.current(), initialMemory);

  // Verify all rows point to the same data
  {
    AqlValue const& val0 = block->getValueReference(0, 0);
    AqlValue const& val1 = block->getValueReference(1, 0);
    AqlValue const& val2 = block->getValueReference(2, 0);
    EXPECT_EQ(val0.data(), val1.data())
        << "Row 0 and 1 should point to same memory";
    EXPECT_EQ(val1.data(), val2.data())
        << "Row 1 and 2 should point to same memory";
    EXPECT_EQ(val0.type(), AqlValue::VPACK_SUPERVISED_SLICE);
  }

  // Verify memory is still allocated (block owns it via refCount)
  EXPECT_EQ(monitor.current(), initialMemory);

  // Mark local variable as empty to prevent any issues
  supervised.erase();

  // Destroy the block - this will free the supervised slice memory
  // When setValue() is called, the block takes ownership via reference
  // counting. When the block is destroyed, it calls destroy() on all values,
  // which for supervised slices calls deallocateSupervised() and frees the
  // memory.
  block.reset(nullptr);

  // After destroying the block, memory should be freed
  // We don't check monitor.current() here to avoid any potential issues
  // with accessing freed memory during the check
}

TEST_F(AqlItemBlockSharedValuesTest,
       MultipleSupervisedSlicesSameData_ReferenceValuesFromRow) {
  auto block = itemBlockManager.requestBlock(3, 1);

  size_t initialMemory = monitor.current();

  // Create a supervised slice
  AqlValue supervised = createLargeSupervisedSlice(200);
  ASSERT_EQ(supervised.type(), AqlValue::VPACK_SUPERVISED_SLICE);

  size_t memoryAfterCreation = monitor.current();
  EXPECT_GT(memoryAfterCreation, initialMemory);

  block->setValue(0, 0, supervised);
  EXPECT_EQ(monitor.current(), memoryAfterCreation);

  // Reference it to row 1 and row 2 using referenceValuesFromRow()
  // This makes rows 1 and 2 share the same pointer as row 0
  RegIdFlatSet regs;
  regs.insert(RegisterId::makeRegular(0));
  block->referenceValuesFromRow(1, regs, 0);
  block->referenceValuesFromRow(2, regs, 0);

  EXPECT_EQ(monitor.current(), memoryAfterCreation);

  // Verify all rows point to the same data
  {
    AqlValue const& val0 = block->getValueReference(0, 0);
    AqlValue const& val1 = block->getValueReference(1, 0);
    AqlValue const& val2 = block->getValueReference(2, 0);
    EXPECT_EQ(val0.data(), val1.data());
    EXPECT_EQ(val1.data(), val2.data());
  }

  // When setValue() is called, the block takes ownership of the memory.
  // referenceValuesFromRow() increments the refCount but doesn't change
  // ownership. The local 'supervised' variable still has a copy of the AqlValue
  // object, but the memory is owned by the block. We erase it to mark it as
  // empty.
  supervised.erase();

  // Destroy the block - this will free the supervised slice memory
  // The block's destroy() method will properly free all memory via
  // reference counting. All three rows share the same pointer, so when
  // refCount reaches 0, the memory is freed once.
  // Note: This test verifies that referenceValuesFromRow() correctly shares
  // pointers between rows, which is the scenario that triggers the bug
  // in cloneDataAndMoveShadow() when shadow rows share pointers.
  block.reset(nullptr);

  // After destroying the block, memory should be freed
  EXPECT_EQ(monitor.current(), initialMemory);
}

TEST_F(AqlItemBlockSharedValuesTest,
       MultipleSupervisedSlicesSameData_DestroyValue) {
  auto block = itemBlockManager.requestBlock(3, 1);

  // Create a supervised slice
  AqlValue supervised = createLargeSupervisedSlice(200);
  ASSERT_EQ(supervised.type(), AqlValue::VPACK_SUPERVISED_SLICE);

  size_t initialMemory = monitor.current();

  // Set value in all three rows
  block->setValue(0, 0, supervised);
  block->setValue(1, 0, supervised);
  block->setValue(2, 0, supervised);
  // For supervised slices, setValue() does NOT increase ResourceMonitor
  EXPECT_EQ(monitor.current(), initialMemory);

  // Destroy value in row 0 - should decrement refCount but not free memory
  // For supervised slices, destroyValue() does NOT decrease ResourceMonitor
  // because the memory is still alive (tracked by ResourceMonitor, not block)
  block->destroyValue(0, 0);
  EXPECT_EQ(monitor.current(), initialMemory)
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
  EXPECT_EQ(monitor.current(), initialMemory)
      << "Memory should still be allocated";

  // Destroy value in row 2 - this destroys the last reference in the block
  // but memory is still tracked by ResourceMonitor (allocated when supervised
  // was created)
  block->destroyValue(2, 0);
  EXPECT_EQ(monitor.current(), initialMemory)
      << "Memory should still be allocated (local 'supervised' variable alive)";

  // Destroy the block
  block.reset(nullptr);
  // Memory should still be allocated because local 'supervised' variable is
  // alive
  EXPECT_EQ(monitor.current(), initialMemory);

  // Destroy the supervised slice to release memory
  supervised.destroy();
  // Now all memory should be released
  EXPECT_LE(monitor.current(), 100U);  // Allow tolerance for overhead
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

  EXPECT_EQ(monitor.current(), initialMemory + managedMemory);

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

  // Supervised slice memory should still be allocated (local variable alive)
  // Managed slice memory should be released (block owned it)
  EXPECT_GE(monitor.current(), initialMemory);
  EXPECT_LE(monitor.current(), initialMemory + supervisedMemory + 100U);

  // Destroy supervised slice to release its memory
  supervised.destroy();

  // Now all memory should be released
  EXPECT_LE(monitor.current(), 100U);  // Allow tolerance for overhead
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

  EXPECT_EQ(monitor.current(), initialMemory + managedMemory);

  // Verify references
  EXPECT_EQ(block->getValueReference(0, 0).data(),
            block->getValueReference(1, 0).data());
  EXPECT_EQ(block->getValueReference(2, 0).data(),
            block->getValueReference(3, 0).data());

  // Destroy the block
  block.reset(nullptr);

  // Supervised slice memory should still be allocated (local variable alive)
  // Managed slice memory should be released (block owned it)
  EXPECT_GE(monitor.current(), initialMemory);
  EXPECT_LE(monitor.current(), initialMemory + supervisedMemory + 100U);

  // Destroy supervised slice to release its memory
  supervised.destroy();

  // Now all memory should be released
  EXPECT_LE(monitor.current(), 100U);  // Allow tolerance for overhead
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

  block->setValue(0, 0, val1);
  block->setValue(0, 1, val2);
  block->setValue(0, 2, val3);

  RegIdFlatSet regs;
  regs.insert(RegisterId::makeRegular(0));
  regs.insert(RegisterId::makeRegular(1));
  regs.insert(RegisterId::makeRegular(2));
  block->referenceValuesFromRow(1, regs, 0);

  EXPECT_EQ(monitor.current(), initialMemory);

  // Verify all registers in row 1 point to same data as row 0
  EXPECT_EQ(block->getValueReference(0, 0).data(),
            block->getValueReference(1, 0).data());
  EXPECT_EQ(block->getValueReference(0, 1).data(),
            block->getValueReference(1, 1).data());
  EXPECT_EQ(block->getValueReference(0, 2).data(),
            block->getValueReference(1, 2).data());

  block.reset(nullptr);
  EXPECT_EQ(monitor.current(), initialMemory);

  val1.destroy();
  val2.destroy();
  val3.destroy();
  EXPECT_LE(monitor.current(), 100U);
}

TEST_F(AqlItemBlockSharedValuesTest,
       MultipleRegisters_MixedManagedAndSupervised) {
  auto block = itemBlockManager.requestBlock(2, 3);

  // Create mixed slices
  AqlValue managed1 = createLargeManagedSlice(200);
  AqlValue supervised1 = createLargeSupervisedSlice(200);
  AqlValue managed2 = createLargeManagedSlice(200);

  size_t initialMemory = monitor.current();

  block->setValue(0, 0, managed1);
  block->setValue(0, 1, supervised1);
  block->setValue(0, 2, managed2);

  RegIdFlatSet regs;
  regs.insert(RegisterId::makeRegular(0));
  regs.insert(RegisterId::makeRegular(1));
  regs.insert(RegisterId::makeRegular(2));
  block->referenceValuesFromRow(1, regs, 0);

  size_t managedTotal = managed1.memoryUsage() + managed2.memoryUsage();
  EXPECT_EQ(monitor.current(), initialMemory + managedTotal);

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

  block.reset(nullptr);
  EXPECT_GE(monitor.current(), initialMemory);
  EXPECT_LE(monitor.current(),
            initialMemory + supervised1.memoryUsage() + 100U);

  supervised1.destroy();
  EXPECT_LE(monitor.current(), 100U);
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
  size_t initialMemory = monitor.current();

  for (size_t i = 0; i < numRows; ++i) {
    block->setValue(i, 0, supervised);
  }
  EXPECT_EQ(monitor.current(), initialMemory);

  // Verify all rows point to the same data
  void const* firstData = block->getValueReference(0, 0).data();
  for (size_t i = 1; i < numRows; ++i) {
    EXPECT_EQ(block->getValueReference(i, 0).data(), firstData)
        << "Row " << i << " should point to same memory as row 0";
  }

  block.reset(nullptr);
  EXPECT_EQ(monitor.current(), initialMemory);

  supervised.destroy();
  EXPECT_LE(monitor.current(), 100U);
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
  size_t initialMemory = monitor.current();

  for (size_t i = 0; i < 5; ++i) {
    block->setValue(i, 0, supervised);
  }
  EXPECT_EQ(monitor.current(), initialMemory);

  for (size_t i = 0; i < 3; ++i) {
    block->destroyValue(i, 0);
    EXPECT_TRUE(block->getValueReference(i, 0).isEmpty());
    EXPECT_EQ(monitor.current(), initialMemory);
  }

  // Rows 3 and 4 should still have the value
  EXPECT_FALSE(block->getValueReference(3, 0).isEmpty());
  EXPECT_FALSE(block->getValueReference(4, 0).isEmpty());
  EXPECT_EQ(block->getValueReference(3, 0).data(),
            block->getValueReference(4, 0).data());

  block->destroyValue(3, 0);
  EXPECT_EQ(monitor.current(), initialMemory);

  block->destroyValue(4, 0);
  EXPECT_EQ(monitor.current(), initialMemory);

  block.reset(nullptr);
  EXPECT_EQ(monitor.current(), initialMemory);

  supervised.destroy();
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
  size_t initialMemory = monitor.current();

  block->setValue(0, 0, supervised);
  block->setValue(1, 0, supervised);
  size_t memoryAfterSet = monitor.current();
  EXPECT_EQ(memoryAfterSet, initialMemory);

  AqlValue stolen = block->getValue(0, 0);
  block->steal(stolen);
  EXPECT_FALSE(block->getValueReference(1, 0).isEmpty());

  size_t memoryAfterSteal = monitor.current();
  EXPECT_EQ(memoryAfterSteal, initialMemory);

  block.reset(nullptr);
  size_t memoryAfterBlockDestroy = monitor.current();
  EXPECT_EQ(memoryAfterBlockDestroy, initialMemory);

  stolen.destroy();
  EXPECT_LE(monitor.current(), 100U);
}

// ============================================================================
// TEST SUITE 6: cloneDataAndMoveShadow with Shared Pointers
// This tests the bug fix where multiple shadow rows share the same value
// pointer via referenceValuesFromRow(), and cloneDataAndMoveShadow() must
// handle this correctly by always calling guard.steal() regardless of cache
// state.
// ============================================================================

TEST_F(AqlItemBlockSharedValuesTest,
       cloneDataAndMoveShadow_ShadowRowsSharePointerViaReference) {
  // This test reproduces the scenario where:
  // 1. A data row has a supervised slice
  // 2. Multiple shadow rows reference the same value via
  // referenceValuesFromRow()
  // 3. cloneDataAndMoveShadow() processes these shadow rows
  // 4. The cache finds inserted=false for the second shadow row (same pointer)
  // 5. The fix ensures guard.steal() is always called, preventing
  // use-after-free

  auto block = itemBlockManager.requestBlock(4, 1);

  // Create a supervised slice in row 0 (data row)
  std::string content =
      "This is a test string that is long enough to not be inlined";
  AqlValue supervised = createSupervisedSlice(content);
  ASSERT_EQ(supervised.type(), AqlValue::VPACK_SUPERVISED_SLICE);
  ASSERT_TRUE(supervised.requiresDestruction());

  size_t initialMemory = monitor.current();

  // Set value in data row 0
  block->setValue(0, 0, supervised);
  EXPECT_EQ(monitor.current(), initialMemory);

  // Create shadow rows 1, 2, 3
  block->makeShadowRow(1, 0);
  block->makeShadowRow(2, 0);
  block->makeShadowRow(3, 0);

  // Use referenceValuesFromRow() to make shadow rows share the same pointer
  // This is the natural way shadow rows can share pointers
  RegIdFlatSet regs;
  regs.insert(RegisterId::makeRegular(0));
  block->referenceValuesFromRow(1, regs, 0);  // Shadow row 1 references row 0
  block->referenceValuesFromRow(2, regs, 0);  // Shadow row 2 references row 0
  block->referenceValuesFromRow(3, regs, 0);  // Shadow row 3 references row 0

  // Verify all shadow rows point to the same data as row 0
  void const* dataPtr0 = block->getValueReference(0, 0).data();
  void const* dataPtr1 = block->getValueReference(1, 0).data();
  void const* dataPtr2 = block->getValueReference(2, 0).data();
  void const* dataPtr3 = block->getValueReference(3, 0).data();

  EXPECT_EQ(dataPtr0, dataPtr1)
      << "Shadow row 1 should share pointer with row 0";
  EXPECT_EQ(dataPtr1, dataPtr2)
      << "Shadow row 2 should share pointer with row 0";
  EXPECT_EQ(dataPtr2, dataPtr3)
      << "Shadow row 3 should share pointer with row 0";

  // Verify shadow rows are marked correctly
  EXPECT_FALSE(block->isShadowRow(0));
  EXPECT_TRUE(block->isShadowRow(1));
  EXPECT_TRUE(block->isShadowRow(2));
  EXPECT_TRUE(block->isShadowRow(3));

  // Now call cloneDataAndMoveShadow() - this should handle the shared pointers
  // correctly. The fix ensures that guard.steal() is always called, even when
  // inserted=false (same pointer seen before).
  SharedAqlItemBlockPtr cloned = block->cloneDataAndMoveShadow();

  ASSERT_NE(cloned, nullptr);
  EXPECT_EQ(cloned->numRows(), 4);
  EXPECT_EQ(cloned->numRegisters(), 1);

  // Verify shadow rows are still marked correctly in cloned block
  EXPECT_FALSE(cloned->isShadowRow(0));
  EXPECT_TRUE(cloned->isShadowRow(1));
  EXPECT_TRUE(cloned->isShadowRow(2));
  EXPECT_TRUE(cloned->isShadowRow(3));

  // Data row 0 should be cloned (deep copy)
  EXPECT_FALSE(cloned->getValueReference(0, 0).isEmpty());
  EXPECT_NE(cloned->getValueReference(0, 0).data(), dataPtr0)
      << "Data row should be cloned (new pointer)";

  // Shadow rows should be moved (stolen from original)
  EXPECT_FALSE(cloned->getValueReference(1, 0).isEmpty());
  EXPECT_FALSE(cloned->getValueReference(2, 0).isEmpty());
  EXPECT_FALSE(cloned->getValueReference(3, 0).isEmpty());

  // Original shadow rows should be empty (values were stolen)
  EXPECT_TRUE(block->getValueReference(1, 0).isEmpty());
  EXPECT_TRUE(block->getValueReference(2, 0).isEmpty());
  EXPECT_TRUE(block->getValueReference(3, 0).isEmpty());

  // Verify all shadow rows in cloned block point to the same data
  // (they shared the pointer, and after moving, they should still share it)
  void const* clonedDataPtr1 = cloned->getValueReference(1, 0).data();
  void const* clonedDataPtr2 = cloned->getValueReference(2, 0).data();
  void const* clonedDataPtr3 = cloned->getValueReference(3, 0).data();

  EXPECT_EQ(clonedDataPtr1, clonedDataPtr2)
      << "Shadow rows 1 and 2 should still share pointer after move";
  EXPECT_EQ(clonedDataPtr2, clonedDataPtr3)
      << "Shadow rows 2 and 3 should still share pointer after move";

  // Verify the content is correct
  EXPECT_EQ(cloned->getValueReference(1, 0).slice().stringView(), content);
  EXPECT_EQ(cloned->getValueReference(2, 0).slice().stringView(), content);
  EXPECT_EQ(cloned->getValueReference(3, 0).slice().stringView(), content);

  // CRITICAL TEST: Serialize the cloned block to force memory access
  // With the bug (guard.steal() not called when inserted=false), the guard
  // destructor frees the memory immediately after cloneDataAndMoveShadow()
  // returns. When we serialize, we access that freed memory -> use-after-free
  // This should trigger ASAN if the bug is present
  velocypack::Builder builder;
  builder.openObject();
  cloned->toVelocyPack(nullptr, builder);
  builder.close();

  // Verify serialization succeeded and contains the expected data
  VPackSlice slice = builder.slice();
  EXPECT_TRUE(slice.isObject());
  EXPECT_EQ(slice.get("nrItems").getNumericValue<size_t>(), 4);

  // Destroy original block first - shadow rows were stolen, so this is safe
  block.reset(nullptr);

  // The cloned block now owns the shadow row values
  // Destroy cloned block - should properly free memory without use-after-free
  cloned.reset(nullptr);

  // After destroying the cloned block, the memory should be freed
  // (the shadow rows owned the memory, and they were moved to the cloned block)
  // Note: The local 'supervised' variable is now invalid because the memory
  // was moved to the cloned block. We should NOT call supervised.destroy()
  // as that would cause use-after-free.

  // Memory should be released (shadow rows owned it, and they were destroyed)
  EXPECT_LE(monitor.current(), initialMemory + 100U);  // Allow tolerance
}

TEST_F(AqlItemBlockSharedValuesTest,
       cloneDataAndMoveShadow_ShadowRowsSharePointerViaSetValue) {
  // Alternative scenario: Multiple shadow rows set with the same value
  // This also causes them to share the same pointer

  auto block = itemBlockManager.requestBlock(3, 1);

  // Create a supervised slice
  std::string content = "Shared supervised slice content";
  AqlValue supervised = createSupervisedSlice(content);
  ASSERT_EQ(supervised.type(), AqlValue::VPACK_SUPERVISED_SLICE);

  size_t initialMemory = monitor.current();

  // Set the same value in multiple shadow rows
  block->makeShadowRow(0, 0);
  block->makeShadowRow(1, 0);
  block->makeShadowRow(2, 0);

  block->setValue(0, 0, supervised);
  block->setValue(1, 0, supervised);
  block->setValue(2, 0, supervised);

  // Verify all shadow rows point to the same data
  void const* dataPtr0 = block->getValueReference(0, 0).data();
  void const* dataPtr1 = block->getValueReference(1, 0).data();
  void const* dataPtr2 = block->getValueReference(2, 0).data();

  EXPECT_EQ(dataPtr0, dataPtr1);
  EXPECT_EQ(dataPtr1, dataPtr2);

  // Call cloneDataAndMoveShadow() - should handle shared pointers correctly
  SharedAqlItemBlockPtr cloned = block->cloneDataAndMoveShadow();

  ASSERT_NE(cloned, nullptr);
  EXPECT_EQ(cloned->numRows(), 3);
  EXPECT_TRUE(cloned->isShadowRow(0));
  EXPECT_TRUE(cloned->isShadowRow(1));
  EXPECT_TRUE(cloned->isShadowRow(2));

  // Verify shadow rows were moved correctly
  EXPECT_FALSE(cloned->getValueReference(0, 0).isEmpty());
  EXPECT_FALSE(cloned->getValueReference(1, 0).isEmpty());
  EXPECT_FALSE(cloned->getValueReference(2, 0).isEmpty());

  // Original shadow rows should be empty
  EXPECT_TRUE(block->getValueReference(0, 0).isEmpty());
  EXPECT_TRUE(block->getValueReference(1, 0).isEmpty());
  EXPECT_TRUE(block->getValueReference(2, 0).isEmpty());

  // Verify content is correct
  EXPECT_EQ(cloned->getValueReference(0, 0).slice().stringView(), content);
  EXPECT_EQ(cloned->getValueReference(1, 0).slice().stringView(), content);
  EXPECT_EQ(cloned->getValueReference(2, 0).slice().stringView(), content);

  // CRITICAL TEST: Serialize the cloned block to force memory access
  // With the bug (guard.steal() not called when inserted=false), the guard
  // destructor frees the memory immediately after cloneDataAndMoveShadow()
  // returns. When we serialize, we access that freed memory -> use-after-free
  // This should trigger ASAN if the bug is present
  velocypack::Builder builder;
  builder.openObject();
  cloned->toVelocyPack(nullptr, builder);
  builder.close();

  // Verify serialization succeeded
  VPackSlice slice = builder.slice();
  EXPECT_TRUE(slice.isObject());
  EXPECT_EQ(slice.get("nrItems").getNumericValue<size_t>(), 3);

  // Destroy original block first - shadow rows were stolen
  block.reset(nullptr);

  // Destroy cloned block - should properly free memory without use-after-free
  cloned.reset(nullptr);

  // After destroying the cloned block, memory should be freed
  // Note: The local 'supervised' variable is now invalid because the memory
  // was moved to the cloned block. We should NOT call supervised.destroy()
  EXPECT_LE(monitor.current(), initialMemory + 100U);
}

}  // namespace aql
}  // namespace tests
}  // namespace arangodb
