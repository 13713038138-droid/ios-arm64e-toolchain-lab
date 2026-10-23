import Foundation

struct Item { let minY: Double; let maxY: Double }
func baseline(_ items: [Item], _ top: Double, _ bottom: Double) -> [Int] {
    var result: [Int] = []
    for (i, item) in items.enumerated() {
        if item.maxY < top { continue }
        if item.minY > bottom { break }
        result.append(i)
    }
    return result
}
func optimized(_ items: [Item], _ top: Double, _ bottom: Double, monotone: Bool) -> ([Int], Int) {
    if !monotone { return (baseline(items, top, bottom), items.count) }
    var low = 0, high = items.count, reads = 0
    while low < high {
        let mid = low + (high - low) / 2
        reads += 1
        if items[mid].maxY < top { low = mid + 1 } else { high = mid }
    }
    var result: [Int] = []
    var index = low
    while index < items.count {
        reads += 1
        if items[index].minY > bottom { break }
        result.append(index)
        index += 1
    }
    return (result, reads)
}
var validations = 0
func check(_ items: [Item], _ top: Double, _ bottom: Double, monotone: Bool = true) {
    let expected = baseline(items, top, bottom)
    let got = optimized(items, top, bottom, monotone: monotone).0
    precondition(expected == got, "Mismatch top=\(top) bottom=\(bottom), count=\(items.count)")
    validations += 1
}
check([],0,100)
check([Item(minY:0,maxY:0)],0,0)
check([Item(minY:0,maxY:10),Item(minY:10,maxY:10),Item(minY:10,maxY:20)],10,10)
check([Item(minY:100,maxY:80),Item(minY:10,maxY:30)],20,90,monotone:false)
var items: [Item] = []
var pos = 0.0
for i in 0..<20_000 {
    let height = i % 17 == 0 ? 0 : Double(11 + (i * 73) % 281)
    items.append(Item(minY:pos,maxY:pos+height))
    pos += height + Double(i % 3)
}
var totalFastReads = 0
for i in 0..<5_000 {
    let top = (Double((i*7919)%20000) / 20000) * pos - 25.0
    let bottom = top + Double(0 + ((i*97)%2000))
    check(items,top,bottom)
    totalFastReads += optimized(items,top,bottom,monotone:true).1
}
precondition(totalFastReads < 5_000 * 200, "Lower bound unexpectedly scans history")
print("PASS visible-range comparisons=\(validations) avg optimized visited=\(Double(totalFastReads)/5000) of \(items.count) historical items")
