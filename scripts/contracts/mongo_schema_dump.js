// Deterministic MongoDB schema dump for contract freezing.
// Run with: mongo --quiet <db> mongo_schema_dump.js
// Prints collections, indexes (incl. geospatial), and BSON field types of one sample document.
var collections = db.getCollectionNames().sort();
collections.forEach(function (name) {
    print('== COLLECTION: ' + name + ' ==');
    var indexes = db.getCollection(name).getIndexes().sort(function (a, b) {
        return a.name < b.name ? -1 : 1;
    });
    indexes.forEach(function (idx) {
        print('index|' + idx.name + '|' + JSON.stringify(idx.key));
    });
    var sample = db.getCollection(name).findOne();
    if (sample !== null) {
        Object.keys(sample).sort().forEach(function (field) {
            var value = sample[field];
            var type = value === null ? 'null'
                : (value instanceof ObjectId) ? 'objectId'
                : (value instanceof Date) ? 'date'
                : (value instanceof NumberLong) ? 'long'
                : Array.isArray(value) ? 'array'
                : typeof value;
            print('field|' + field + '|' + type);
        });
    }
});
