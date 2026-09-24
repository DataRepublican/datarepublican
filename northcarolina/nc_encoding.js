class EncodedAttribute {
	constructor(myid, name, bit_pos, bit_num, bit_map, readable_map) {
		this.name = name;
		this.id = myid;
		this.bit_map = bit_map;
		this.bit_pos = bit_pos;
		this.bit_num = bit_num;
		this.readable_map = readable_map;
		$.each(readable_map, function(k, v) {
			if (!(k in bit_map)) {
				console.error(k + " in readable_map but not bit_map");
			}
		});
		$.each(bit_map, function(k, v) {
			if (!(k in readable_map)) {
				console.error(k + " in bit_map but not readable_map");
			}
		});
	}
	
	readable(attr) {
		if (!(attr in this.readable_map)) {
			console.error("Missing k: " + attr);
		}
		return this.readable_map[attr];
	}
	
	decode(encoded_value) {
		return (encoded_value >>> this['bit_pos']) & ((1 << this['bit_num']) - 1);
	}
	
	matches(encoded_value, attr) {
		if (!(attr in this['bit_map'])) {
			console.log("Unknown attribute: " + attr);
			return false;
		}
		constected = this['bit_map'][attr];
		return this.decode(encoded_value) == expected;
	}
	
	extract(encoded_value) {
		var found = null;
		var obj = this;
		const decoded = obj.decode(encoded_value);
		
		$.each(obj['bit_map'], function (k, v) {
			if (v == decoded) {
				found = k;
				return false;
			}
		}); 
		return found;
	}
	
	extract_readable(encoded_value) {
		const attr = this.extract(encoded_value);
		return attr ? this.readable(attr) : "<none>";
	}
}

const PARTY_ENCODING = new EncodedAttribute('Party', 'Party', 29, 2, {
	'Dem' : 0,
	'Rep' : 1,
	'UNA' : 2
}, {
	'Dem' : 'Democrat',
	'Rep' : 'Republican',
	'UNA' : 'Unaffliated'
});

// The only one initialized as a var array 
var COUNTY_ENCODING = null;

const GENDER_ENCODING = new EncodedAttribute('Gender', 'Gender', 17, 2, {
	'F' : 1,
	'M' : 2	
}, {
	'F': 'female',
	'M': 'male'
});

const RACE_ENCODING = new EncodedAttribute('Race', 'Race', 15, 2, {
	'B' : 1,
	'W' : 2,
	//'undesignated' : 3,
}, {
	'B' : 'black',
	'W' : 'white'
});

const ETHNICITY_ENCODING = new EncodedAttribute('Ethnicity', 'Ethnicity', 13, 2, {
	'H' : 1,
	'N' : 2
}, {
	'H' : 'Hispanic',
	'N' : 'Non-Hispanic'
});

const AGE_ENCODING = new EncodedAttribute('Age', 'Age', 19, 3, {
	"18" : 1,
	"26" : 2,
	"41" : 3,
	"65" : 4,
}, {
	"18" : "18 to 25 years old",
	"26" : "26 to 40 years old",
	"41" : "41 to 64 years old",
	"65" : "65+ years old"
});

// One row set per election; the page picks 2026 as the numerator and one baseline as the denominator.
const ELECTION_ENCODING = new EncodedAttribute('Election', 'Election', 11, 2, {
	'2026' : 0,
	'2024' : 1,
	'2022' : 2
}, {
	'2026' : '2026 general',
	'2024' : '2024 general',
	'2022' : '2022 general'
});

const METHOD_ENCODING = new EncodedAttribute('Method', 'Voting Method', 9, 2, {
	'VBM' : 1,
	'IPEV' : 2
}, {
	'VBM' : 'Mail voter (VBM)',
	'IPEV' : 'In-Person Early voter (IPEV)',
});

// Returned by the same number of days before Election Day as the latest 2026 return. Always 1 for 2026.
const SAME_POINT_ENCODING = new EncodedAttribute('SamePoint', 'Same point', 8, 1, {
	'True' : 1,
	'False' : 0
}, {
	'True' : 'Returned by the same point',
	'False' : 'Returned later'
});

const BITMAP_BOOLEAN = {
	'True': 1,
	'False': 0
};

const VOTED_2016_ENCODING = new EncodedAttribute('Voted2016', 'Voted in 2016', 6, 1, BITMAP_BOOLEAN, {
	'True' : 'Voted in 2016',
	'False' : 'Did not vote in 2016'
});

const VOTED_2018_ENCODING = new EncodedAttribute('Voted2018', 'Voted in 2018', 5, 1, BITMAP_BOOLEAN, {
	'True' : 'Voted in 2018',
	'False' : 'Did not vote in 2018'
});

const VOTED_2022_ENCODING = new EncodedAttribute('Voted2022', 'Voted in 2022', 3, 1, BITMAP_BOOLEAN, {
	'True' : 'Voted in 2022',
	'False' : 'Did not vote in 2022'
});

const VOTED_2020_ENCODING = new EncodedAttribute('Voted2020', 'Voted in 2020', 4, 1, BITMAP_BOOLEAN, {
	'True' : 'Voted in 2020',
	'False' : 'Did not vote in 2020'
});

const VOTED_2024_ENCODING = new EncodedAttribute('Voted2024', 'Voted in 2024', 2, 1, BITMAP_BOOLEAN, {
	'True' : 'Voted in 2024',
	'False' : 'Did not vote in 2024'
});


// for debugging
function dec2bin(dec) {
    return (dec >>> 0).toString(2);
}

// for debugging
function dumpRow(encoded) {
	console.log(encoded)
	const p = PARTY_ENCODING.extract_readable(encoded);
	//const c = COUNTY_ENCODING.extract_readable(encoded);
	const g = GENDER_ENCODING.extract_readable(encoded);
	const r = RACE_ENCODING.extract_readable(encoded);
	const e = ETHNICITY_ENCODING.extract_readable(encoded);
	const a = AGE_ENCODING.extract_readable(encoded);
	const el = ELECTION_ENCODING.extract_readable(encoded);
	const m = METHOD_ENCODING.extract_readable(encoded);
	const sp = SAME_POINT_ENCODING.extract_readable(encoded);
	const d16 = VOTED_2016_ENCODING.extract_readable(encoded);
	const d18 = VOTED_2018_ENCODING.extract_readable(encoded);
	const d20 = VOTED_2020_ENCODING.extract_readable(encoded);
	const d22 = VOTED_2022_ENCODING.extract_readable(encoded);
	const d24 = VOTED_2024_ENCODING.extract_readable(encoded);
	
	const debug_str = "decoded: p:" + p + " g:" + g + 
		" r:" + r + " e:" + e + " a:" + a + " el:" + el + " m:" + m + " sp:" + sp + 
		" d16:" + d16 + " d18:" + d18 + " d20:" + d20 + " d22:" + d22 + 
		" d24:" + d24;
	console.log(debug_str); 
	// 273891476
	// decoded: decoded: p:D c:new hanover a:26 g:F r:WHITE e:NOT HISPANIC v22: v24:MAIL 16:0 18:0 20:1 22:0 24:1
	//catawba a:65 g:M r:WHITE e:NOT HISPANIC v16: v20:IPEV 12:0 14:0 16:0 18:0 20:1
}

// county intentionally excluded because we don't want a 100 box checklist.
var encodings = {
};

/** call this on start. Expects a list of sorted counties. */
function initializeEncoded(sortedCounties) {
	var bitmap_county = {};
	for (var i = 0; i < sortedCounties.length; ++i) {
		bitmap_county[sortedCounties[i]] = i+1;
	}
	//dumpRow(273891476);
	//dumpRow(1346766968);

	var readable = {};
	$.each(bitmap_county, function(k, v) {
		readable[k] = k;
	});
	COUNTY_ENCODING = new EncodedAttribute('County', 'County', 22, 7, bitmap_county, readable);
	//console.log(COUNTY_ENCODING)

	encodings[AGE_ENCODING['id']] = AGE_ENCODING;
	encodings[GENDER_ENCODING['id']] = GENDER_ENCODING;
	encodings[RACE_ENCODING['id']] = RACE_ENCODING;
	encodings[ETHNICITY_ENCODING['id']] = ETHNICITY_ENCODING;
	encodings[VOTED_2016_ENCODING['id']] = VOTED_2016_ENCODING;
	encodings[VOTED_2018_ENCODING['id']] = VOTED_2018_ENCODING;
	encodings[VOTED_2020_ENCODING['id']] = VOTED_2020_ENCODING;
	encodings[VOTED_2022_ENCODING['id']] = VOTED_2022_ENCODING;
	encodings[VOTED_2024_ENCODING['id']] = VOTED_2024_ENCODING;
	
	/*
	// testing code... 
	const encoded = 614809860;
	// should return:
	// decoded: p:R c:catawba a:65 g:M r:WHITE e:NOT HISPANIC v16: v20:IPEV 12:0 14:0 16:0 18:0 20:1
	console.log("exp: 100100101001010100000100000100"); 
	const bin = dec2bin(encoded);
	console.log("got:" + bin + " " + (bin==="100100101001010100000100000100"));	
	dumpRow(encoded);
	*/
}

