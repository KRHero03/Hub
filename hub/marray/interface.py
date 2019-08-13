from bbox import Bbox, chunknames, shade, Vec, generate_chunks
from pathos.threading import ThreadPool
from storage import Storage, S3
import numpy as np
from hub.log import logger

class TensorInterface(object):
    def __init__(self, shape=None, chunk_shape=None, dtype=None, key=None, protocol=None, parallel=True):
        self.shape = shape
        self.chunk_shape = chunk_shape
        self.dtype = dtype
        self.key = key
        self.protocol = protocol
        self.storage = S3(self.key)
        self.order = 'F'

        if parallel == False:
            parallel = 1
        if parallel == True:
            parallel = 20

        self.pool = ThreadPool(nodes=parallel)

    def generate_cloudpaths(self, slices):
        # Slices -> Bbox
        slices = Bbox(Vec.zeros(self.shape), self.shape).reify_slices(slices)
        requested_bbox = Bbox.from_slices(slices)

        # Make sure chunks fit
        full_bbox = requested_bbox.expand_to_chunk_size(
            self.chunk_shape, offset = Vec.zeros(self.shape)
        )

        # Clamb the border
        full_bbox = Bbox.clamp(full_bbox, Bbox(Vec.zeros(self.shape), self.shape))

        # Generate chunknames
        cloudpaths = list(chunknames(
            full_bbox, self.shape, 
            self.key, self.chunk_shape, 
            protocol=self.protocol
        ))
        return cloudpaths, requested_bbox 

    # read from raw file and transform to numpy array 
    def decode(self, chunk):
        return np.frombuffer(bytearray(chunk), dtype=dtype).reshape(self.chunk_shape, order='F')

    def download_chunk(self, cloudpath):
        chunk = self.storage.get(cloudpath)
        if chunk:
            chunk = self.decode(chunk)
        else: 
            chunk = np.zeros(shape=self.chunk_shape, dtype=self.dtype, order=self.order)
        bbox = Bbox.from_filename(cloudpath)
        return chunk, bbox

    def download(self, cloudpaths, requested_bbox):
        # Download chunks
        chunks_bboxs = self.pool.map(self.download_chunk, cloudpaths)

        # Combine Chunks
        renderbuffer = np.zeros(shape=requested_bbox.to_shape(), dtype=self.dtype, order=self.order)
        def process(chunk_bbox):
            chunk, bbox = chunk_bbox
            shade(renderbuffer, requested_bbox, chunk, bbox)
        self.pool.map(process, chunks_bboxs)

        return renderbuffer

    def __getitem__(self, slices):
        cloudpaths, requested_bbox = self.generate_cloudpaths(slices)
        tensor = self.download(cloudpaths, requested_bbox)
        return tensor

    def encode(self, chunk):
        return chunk.tostring('F')

    def upload_chunk(self, cloudpath_chunk):
        cloudpath, chunk = cloudpath_chunk
        chunk = self.encode(chunk)
        chunk = self.storage.put(cloudpath, chunk, content_type=None)
        
    def chunkify(self, cloudpaths, requested_bbox, item):
        chunks = []
        for path in cloudpaths:
            cloudchunk = Bbox.from_filename(path)
            intersection = Bbox.intersection(cloudchunk, requested_bbox)
            chunk_slices = (intersection-cloudchunk.minpt).to_slices()
            item_slices = (intersection-cloudchunk.minpt).to_slices()

            chunk = np.zeros(shape=self.chunk_shape, dtype=self.dtype, order=self.order)
            if np.any(np.array(intersection.to_shape()) != np.array(self.chunk_shape)):
                logger.warn('Non aligned write')
                chunk, _ = self.download_chunk(path)
            else:
                chunk = np.zeros(shape=self.chunk_shape, dtype=self.dtype, order=self.order)

            chunk[chunk_slices] = item[item_slices]
            chunks.append(chunk)

        return zip(cloudpaths, chunks)
    
    def upload(self, cloudpaths, requested_bbox, item):
        cloudpaths_chunks = self.chunkify(cloudpaths, requested_bbox, item)
        list(map(self.upload_chunk, list(cloudpaths_chunks)))

    def __setitem__(self, slices, item):
        cloudpaths, requested_bbox = self.generate_cloudpaths(slices)
        self.upload(cloudpaths, requested_bbox, item)

if __name__ == "__main__":
    a = TensorInterface(
            shape=(100,100,100,100,100), 
            chunk_shape=(10,10,10,10,10), 
            dtype='uint8', 
            key='s3://snark-hub-main/imagenet/fake/train'
    )
    a[:10, :10, :10, :10, :10] = np.ones((10,10,10,10,10), dtype='uint8')
    print(a[:10, :10, :10, :10, :10].mean())
    #print(b)
    #a[1:10,:10,:23] = 0
    #a[...] = 0