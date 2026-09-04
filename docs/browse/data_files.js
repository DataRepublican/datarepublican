const FILES_10M = [
  {
    "status": "Loading Charities",
    "baseFile": "/browse/tsv_chunks/charities_chunk_",
    "tsvFilePrefix": "charities_chunk_",
    "type": "charities",
    "chunkCount": 11
  },
  {
    "status": "Loading Grants",
    "baseFile": "/browse/tsv_chunks/grants_final_chunk_",
    "tsvFilePrefix": "grants_final_chunk_",
    "type": "grants",
    "chunkCount": 59,
    "grantType": "regular"
  }
];

export const DATA_FILES = {
  dbVersion: "2026-09-03T17:26:39Z",
  defaultBand: "10M",
  bands: [
    {
      id: "10M",
      label: "$10M",
      threshold: 10000000,
      nodes: 103746,
      grants: 586476,
      dollars: 2405409249784,
      edges: 558647,
      zipBytes: 14122476,
      files: FILES_10M,
    },
    {
      id: "1M",
      label: "$1M",
      threshold: 1000000,
      nodes: 369467,
      grants: 1704820,
      dollars: 2574763247168,
      edges: 1626382,
      zipBytes: 57801192,
      files: [
        {
          status: "Loading Charities ($1M)",
          baseFile: "https://www.grumpytechbro.com/browse/tsv_chunks/1m/charities_chunk_",
          tsvFilePrefix: "charities_chunk_",
          type: "charities",
          chunkCount: 37,
        },
        {
          status: "Loading Grants ($1M)",
          baseFile: "https://www.grumpytechbro.com/browse/tsv_chunks/1m/grants_final_chunk_",
          tsvFilePrefix: "grants_final_chunk_",
          type: "grants",
          chunkCount: 171,
          grantType: "regular",
        },
      ],
    },
    {
      id: "all",
      label: "All",
      threshold: 1,
      nodes: 2618469,
      grants: 5606912,
      dollars: 2600747385432,
      edges: 5586438,
      zipBytes: 363415135,
      files: [
        {
          status: "Loading Charities (All)",
          baseFile: "https://www.grumpytechbro.com/browse/tsv_chunks/all/charities_chunk_",
          tsvFilePrefix: "charities_chunk_",
          type: "charities",
          chunkCount: 262,
        },
        {
          status: "Loading Grants (All)",
          baseFile: "https://www.grumpytechbro.com/browse/tsv_chunks/all/grants_final_chunk_",
          tsvFilePrefix: "grants_final_chunk_",
          type: "grants",
          chunkCount: 561,
          grantType: "regular",
        },
      ],
    },
  ],
  files: FILES_10M,
};
