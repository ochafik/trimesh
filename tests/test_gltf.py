try:
    from . import generic as g
except BaseException:
    import generic as g

# Khronos' official file validator
# can be installed with the helper script:
# `trimesh/docker/builds/gltf_validator.bash`
_gltf_validator = g.find_executable('gltf_validator')


def validate_glb(data):
    """
    Run the Khronos validator on GLB files using
    subprocess.

    Parameters
    ------------
    data : bytes
      GLB export

    Raises
    ------------
    ValueError
      If Khronos validator reports errors.
    """
    if _gltf_validator is None:
        g.log.warning('no gltf_validator!')
        return

    with g.tempfile.NamedTemporaryFile(suffix='.glb') as f:
        f.write(data)
        f.flush()
        # run the khronos gltf-validator
        report = g.subprocess.run(
            [_gltf_validator, f.name, '-o'],
            capture_output=True)
        # -o prints JSON to stdout
        content = report.stdout.decode('utf-8')
        if report.returncode != 0:
            # log the whole error report
            g.log.error(content)
            raise ValueError('Khronos GLTF validator error!')

        # log the GLTF validator report if
        # there are any warnings or hints
        decode = g.json.loads(content)
        if any(decode['issues'][i] > 0 for i in
               ['numWarnings', 'numInfos', 'numHints']):
            g.log.warning(content)


class GLTFTest(g.unittest.TestCase):

    def test_duck(self):
        scene = g.get_mesh('Duck.glb', process=False)

        # should have one mesh
        assert len(scene.geometry) == 1

        # get the mesh
        geom = next(iter(scene.geometry.values()))

        # should not be watertight
        assert not geom.is_volume
        # make sure export doesn't crash
        export = scene.export(file_type='glb')
        validate_glb(export)

        # check a roundtrip
        reloaded = g.trimesh.load(
            g.trimesh.util.wrap_as_stream(export),
            file_type='glb')
        # make basic assertions
        g.scene_equal(scene, reloaded)

        # if we merge ugly it should now be watertight
        geom.merge_vertices(merge_tex=True)
        assert geom.is_volume

    def test_buffer_dedupe(self):
        scene = g.trimesh.Scene()
        box_1 = g.trimesh.creation.box()
        box_2 = g.trimesh.creation.box()
        box_3 = g.trimesh.creation.box()
        box_3.visual.face_colors = [0, 255, 0, 255]

        tm = g.trimesh.transformations.translation_matrix
        scene.add_geometry(
            box_1, 'box_1',
            transform=tm((1, 1, 1)))
        scene.add_geometry(
            box_2, 'box_2',
            transform=tm((-1, -1, -1)))
        scene.add_geometry(
            box_3, 'box_3',
            transform=tm((-1, 20, -1)))
        a = g.json.loads(scene.export(
            file_type='gltf')['model.gltf'].decode('utf-8'))
        assert len(a['buffers']) <= 3

    def test_tex_export(self):
        # load textured PLY
        mesh = g.get_mesh('fuze.ply')
        assert hasattr(mesh.visual, 'uv')

        # make sure export as GLB doesn't crash on scenes
        export = mesh.scene().export(file_type='glb')
        validate_glb(export)
        # make sure it works on meshes
        export = mesh.export(file_type='glb')
        validate_glb(export)

    def test_cesium(self):
        # A GLTF with a multi- primitive mesh

        s = g.get_mesh('CesiumMilkTruck.glb')
        # should be one Trimesh object per GLTF "primitive"
        assert len(s.geometry) == 4
        # every geometry displayed once, except wheels twice
        assert len(s.graph.nodes_geometry) == 5

        # make sure export doesn't crash
        export = s.export(file_type='glb')
        validate_glb(export)

        reloaded = g.trimesh.load(
            g.trimesh.util.wrap_as_stream(export),
            file_type='glb')
        # make basic assertions
        g.scene_equal(s, reloaded)

    def test_units(self):

        # Trimesh will store units as a GLTF extra if they
        # are defined so check that.

        original = g.get_mesh('pins.glb')

        # export it as a a GLB file
        export = original.export(file_type='glb')
        validate_glb(export)
        kwargs = g.trimesh.exchange.gltf.load_glb(
            g.trimesh.util.wrap_as_stream(export))
        # roundtrip it
        reloaded = g.trimesh.exchange.load.load_kwargs(kwargs)
        # make basic assertions
        g.scene_equal(original, reloaded)

        # make assertions on original and reloaded
        for scene in [original, reloaded]:
            # units should be stored as an extra
            assert scene.units == 'mm'

            # make sure we have two unique geometries
            assert len(scene.geometry) == 2
            # that should have seven instances
            assert len(scene.graph.nodes_geometry) == 7

            # all meshes should be well constructed
            assert all(m.is_volume for m in
                       scene.geometry.values())

            # check unit conversions for fun
            extents = scene.extents.copy()
            as_in = scene.convert_units('in')
            # should all be exactly mm -> in conversion factor
            assert g.np.allclose(
                extents / as_in.extents, 25.4, atol=.001)

        m = g.get_mesh('testplate.glb')
        assert m.units == 'meters'

    def test_basic(self):
        # split a multibody mesh into a scene
        scene = g.trimesh.scene.split_scene(
            g.get_mesh('cycloidal.ply'))
        # should be 117 geometries
        assert len(scene.geometry) >= 117

        # a dict with {file name: str}
        export = scene.export(file_type='gltf')
        # load from just resolver
        r = g.trimesh.load(file_obj=None,
                           file_type='gltf',
                           resolver=export)
        # will assert round trip is roughly equal
        g.scene_equal(r, scene)

        # try loading from a ZIP archive
        zipped = g.trimesh.util.compress(export)
        r = g.trimesh.load(
            file_obj=g.trimesh.util.wrap_as_stream(zipped),
            file_type='zip')

        # try loading from a file name
        # will require a file path resolver
        with g.TemporaryDirectory() as d:
            for file_name, data in export.items():
                with open(g.os.path.join(d, file_name), 'wb') as f:
                    f.write(data)
            # load from file path of header GLTF
            rd = g.trimesh.load(
                g.os.path.join(d, 'model.gltf'))
            # will assert round trip is roughly equal
            g.scene_equal(rd, scene)

    def test_merge_buffers(self):
        # split a multibody mesh into a scene
        scene = g.trimesh.scene.split_scene(
            g.get_mesh('cycloidal.ply'))

        # export a gltf with the merge_buffers option set to true
        export = scene.export(file_type='gltf', merge_buffers=True)

        # We should end up with a single .bin and scene.gltf
        assert len(export.keys()) == 2

        # reload the export
        reloaded = g.trimesh.exchange.load.load_kwargs(
            g.trimesh.exchange.gltf.load_gltf(
                file_obj=None,
                resolver=g.trimesh.visual.resolvers.ZipResolver(export)))

        # check to make sure the geometry keys are the same
        assert set(reloaded.geometry.keys()) == set(scene.geometry.keys())

    def test_merge_primitives(self):
        # test to see if the `merge_primitives` logic is working
        a = g.get_mesh('CesiumMilkTruck.glb')
        assert len(a.geometry) == 4

        # should combine the multiple primitives into a single mesh
        b = g.get_mesh('CesiumMilkTruck.glb', merge_primitives=True)
        assert len(b.geometry) == 2

    def test_optional_camera(self):
        gltf_cameras_key = 'cameras'

        # if there's no camera in the scene, then it shouldn't be added to the gltf
        box = g.trimesh.creation.box([1, 1, 1])
        scene = g.trimesh.Scene(box)
        export = scene.export(file_type='gltf')
        assert gltf_cameras_key not in g.json.loads(export['model.gltf'].decode('utf8'))

        # `scene.camera` creates a camera if it does not exist.
        # once in the scene, it should be added to the gltf.
        box = g.trimesh.creation.box([1, 1, 1])
        scene = g.trimesh.Scene(box)
        scene.set_camera()
        export = scene.export(file_type='gltf')
        assert gltf_cameras_key in g.json.loads(export['model.gltf'].decode('utf8'))

    def test_gltf_pole(self):
        scene = g.get_mesh('simple_pole.glb')

        # should have multiple primitives
        assert len(scene.geometry) == 11

        export = scene.export(file_type='glb')
        validate_glb(export)
        # check a roundtrip
        reloaded = g.trimesh.load(
            g.trimesh.util.wrap_as_stream(export),
            file_type='glb')
        # make basic assertions
        g.scene_equal(scene, reloaded)

    def test_material_hash(self):

        # load mesh twice independently
        a = g.get_mesh('fuze.obj')
        b = g.get_mesh('fuze.obj')
        # move one of the meshes away from the other
        a.apply_translation([a.scale, 0, 0])

        # materials should not be the same object
        assert id(a.visual.material) != id(b.visual.material)
        # despite being loaded separately material hash should match
        assert hash(a.visual.material) == hash(b.visual.material)

        # create a scene with two meshes
        scene = g.trimesh.Scene([a, b])
        # get the exported GLTF header of a scene with both meshes
        header = g.json.loads(scene.export(
            file_type='gltf')['model.gltf'].decode('utf-8'))
        # header should contain exactly one material
        assert len(header['materials']) == 1
        # both meshes should be contained in the export
        assert len(header['meshes']) == 2

        # get a reloaded version
        export = scene.export(file_type='glb')
        validate_glb(export)
        reloaded = g.trimesh.load(
            file_obj=g.trimesh.util.wrap_as_stream(export),
            file_type='glb')

        # meshes should have survived
        assert len(reloaded.geometry) == 2
        # get meshes back
        ar, br = reloaded.geometry.values()

        # should have been loaded as a PBR material
        assert isinstance(ar.visual.material,
                          g.trimesh.visual.material.PBRMaterial)

        # materials should have the same memory location
        assert id(ar.visual.material) == id(br.visual.material)

        # make sure hash is returning something
        ahash = hash(ar.visual.material)
        # should be returning valid material hashes
        assert isinstance(ahash, int)
        assert ahash != 0

    def test_node_name(self):
        # Test to see if node names generally survive
        # an export-import cycle.

        # a scene
        s = g.get_mesh('cycloidal.3DXML')
        # export as GLB then re-load
        export = s.export(file_type='glb')
        validate_glb(export)
        r = g.trimesh.load(
            g.trimesh.util.wrap_as_stream(export),
            file_type='glb')
        # make sure we have the same geometries before and after
        assert set(s.geometry.keys()) == set(r.geometry.keys())
        # make sure the node names are the same before and after
        assert (set(s.graph.nodes_geometry) ==
                set(r.graph.nodes_geometry))

    def test_schema(self):
        # get a copy of the GLTF schema and do simple checks
        s = g.trimesh.exchange.gltf.get_schema()

        # make sure it has at least the keys we expect
        assert set(s['properties'].keys()).issuperset(
            {'accessors',
             'animations',
             'asset',
             'buffers',
             'bufferViews',
             'cameras',
             'images',
             'materials',
             'meshes',
             'nodes',
             'samplers',
             'scene',
             'scenes',
             'skins',
             'textures',
             'extensions',
             'extras'})

        # lightly check to see that no references exist
        assert '$ref' not in g.json.dumps(s)

    def test_export_custom_attributes(self):
        # Write and read custom vertex attributes to gltf
        sphere = g.trimesh.primitives.Sphere()
        v_count, _ = sphere.vertices.shape

        sphere.vertex_attributes['_CustomFloat32Scalar'] = g.np.random.rand(
            v_count, 1).astype(
            g.np.float32)
        sphere.vertex_attributes['_CustomUIntScalar'] = g.np.random.randint(
            0, 1000, size=(v_count, 1)
        ).astype(g.np.uintc)
        sphere.vertex_attributes['_CustomFloat32Vec3'] = g.np.random.rand(
            v_count, 3).astype(g.np.float32)
        sphere.vertex_attributes['_CustomFloat32Mat4'] = g.np.random.rand(
            v_count, 4, 4).astype(g.np.float32)

        # export as GLB then re-load
        export = sphere.export(file_type='glb')
        validate_glb(export)
        r = g.trimesh.load(
            g.trimesh.util.wrap_as_stream(export),
            file_type='glb')

        for _, val in r.geometry.items():
            assert set(
                val.vertex_attributes.keys()) == set(
                sphere.vertex_attributes.keys())
            for key in val.vertex_attributes:
                is_same = g.np.array_equal(
                    val.vertex_attributes[key],
                    sphere.vertex_attributes[key])
                assert is_same is True

    def test_extras(self):
        # if GLTF extras are defined, make sure they survive a round trip
        s = g.get_mesh('cycloidal.3DXML')

        # some dummy data
        dummy = {'who': 'likes cheese', 'potatoes': 25}

        # export as GLB with extras passed to the exporter then re-load
        export = s.export(file_type='glb', extras=dummy)
        validate_glb(export)
        r = g.trimesh.load(
            g.trimesh.util.wrap_as_stream(export),
            file_type='glb')

        # shouldn't be in original metadata
        assert 'extras' not in s.metadata
        # make sure extras survived a round trip
        assert all(r.metadata['extras'][k] == v
                   for k, v in dummy.items())

        # now assign the extras to the metadata
        s.metadata['extras'] = dummy
        # export as GLB then re-load
        export = s.export(file_type='glb')
        validate_glb(export)
        r = g.trimesh.load(
            g.trimesh.util.wrap_as_stream(export),
            file_type='glb')
        # make sure extras survived a round trip
        assert all(r.metadata['extras'][k] == v
                   for k, v in dummy.items())

    def test_extras_nodes(self):

        test_metadata = {
            'test_str': 'test_value',
            'test_int': 1,
            'test_float': 0.123456789,
            'test_bool': True,
            'test_array': [1, 2, 3],
            'test_dict': {'a': 1, 'b': 2}}

        sphere1 = g.trimesh.primitives.Sphere(radius=1.0)
        sphere2 = g.trimesh.primitives.Sphere(radius=2.0)

        # transformations.euler_from_quaternion(obj.transform.rotation, axes='sxyz')
        node1_transform = g.trimesh.transformations.translation_matrix([0, 0, -2])
        node2_transform = g.trimesh.transformations.translation_matrix([5, 5, 5])

        s = g.trimesh.scene.Scene()
        s.add_geometry(sphere1, node_name="Sphere1", geom_name="Geom Sphere1",
                       transform=node1_transform, extras=test_metadata)
        s.add_geometry(sphere2, node_name="Sphere2", geom_name="Geom Sphere2",
                       parent_node_name="Sphere1", transform=node2_transform,
                       extras=test_metadata)

        # Test extras appear in the exported model nodes
        files = s.export(None, "gltf")
        gltf_data = files["model.gltf"]
        assert 'test_value' in gltf_data.decode('utf8')

        # Check node extras survive a round trip
        export = s.export(file_type='glb')
        validate_glb(export)
        r = g.trimesh.load(
            g.trimesh.util.wrap_as_stream(export),
            file_type='glb')
        files = r.export(None, "gltf")
        gltf_data = files["model.gltf"]
        assert 'test_value' in gltf_data.decode('utf8')
        edge_data = r.graph.transforms.get_edge_data("world", "Sphere1")
        assert edge_data['extras'] == test_metadata

    def test_read_scene_extras(self):
        # loads a glb with scene extras
        scene = g.get_mesh('monkey.glb', process=False)

        # expected data
        check = {'name': 'monkey', 'age': 32, 'height': 0.987}

        # get the scene extras
        extras = scene.metadata["scene_extras"]

        # check number
        assert len(extras) == 3

        for key in check:
            # \check key existence and value
            assert key in extras
            assert extras[key] == check[key]

    def test_load_empty_nodes(self):
        # loads a glb with no meshes
        scene = g.get_mesh('empty_nodes.glb', process=False)

        # expected data
        check = {"parent": [[1.0, 0.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0, 0.0],
                            [0.0, 0.0, 1.0, 0.0],
                            [0.0, 0.0, 0.0, 1.0]],
                 "children_1": [[1.0, 0.0, 0.0, -5.0],
                                [0.0, 1.0, 0.0, 5.0],
                                [0.0, 0.0, 1.0, 0.0],
                                [0.0, 0.0, 0.0, 1.0]],
                 "children_2": [[1.0, 0.0, 0.0, 5.0],
                                [0.0, 1.0, 0.0, 5.0],
                                [0.0, 0.0, 1.0, 0.0],
                                [0.0, 0.0, 0.0, 1.0]]}

        # get the scene nodes
        objs = scene.graph.to_flattened()

        # check number
        assert len(objs) == 3

        for key in check:
            assert key in objs
            assert objs[key]["transform"] == check[key]

    def test_same_name(self):
        s = g.get_mesh('TestScene.gltf')
        # hardcode correct bounds to check against
        bounds = g.np.array([[-5., -1.82578002, -5.],
                             [5., 1.86791301, 5.]])

        # icosahedrons have two primitives each
        print(len(s.geometry), len(s.graph.nodes_geometry))
        assert len(s.graph.nodes_geometry) == 9
        assert len(s.geometry) == 7
        assert g.np.allclose(s.bounds, bounds, atol=1e-3)

        # if merged should have combined the icosahedrons
        s = g.get_mesh('TestScene.gltf', merge_primitives=True)
        assert len(s.graph.nodes_geometry) == 7
        assert len(s.geometry) == 6
        assert g.np.allclose(s.bounds, bounds, atol=1e-3)

    def test_vertex_colors(self):
        # get a mesh with face colors
        m = g.get_mesh('machinist.XAML')
        # export as GLB then re-import
        export = m.export(file_type='glb')
        validate_glb(export)
        r = next(iter(
            g.trimesh.load(g.trimesh.util.wrap_as_stream(
                export),
                file_type='glb').geometry.values()))
        # original mesh should have vertex colors
        assert m.visual.kind == 'face'
        assert m.visual.vertex_colors.ptp(axis=0).ptp() > 0
        # vertex colors should have survived import-export
        assert g.np.allclose(m.visual.vertex_colors,
                             r.visual.vertex_colors)

    def test_vertex_attrib(self):
        # test concatenation with texture
        m = g.get_mesh('fuze.obj')

        colors = (g.np.random.random(
            (len(m.vertices), 4)) * 255).astype(g.np.uint8)

        # set the color vertex attribute
        m.visual.vertex_attributes['color'] = colors
        export = m.export(file_type='glb')
        validate_glb(export)
        r = next(iter(
            g.trimesh.load(
                g.trimesh.util.wrap_as_stream(export),
                file_type='glb').geometry.values()))

        # make sure the color vertex attributes survived the roundtrip
        assert g.np.allclose(
            r.visual.vertex_attributes['color'], colors)

    def test_export_postprocess(self):
        scene = g.trimesh.Scene()
        sphere = g.trimesh.primitives.Sphere()
        sphere.visual.material = g.trimesh.visual.material.PBRMaterial(name='unlit_test')
        scene.add_geometry(sphere)

        def add_unlit(gltf_tree):
            for material_dict in gltf_tree['materials']:
                if 'unlit' in material_dict.get('name', '').lower():
                    material_dict["extensions"] = {
                        "KHR_materials_unlit": {}
                    }
            gltf_tree["extensionsUsed"] = ["KHR_materials_unlit"]

        gltf_1 = g.trimesh.exchange.gltf.export_gltf(scene)
        gltf_2 = g.trimesh.exchange.gltf.export_gltf(scene, tree_postprocessor=add_unlit)

        def extract_materials(gltf_files):
            return g.json.loads(gltf_files['model.gltf'].decode('utf8'))['materials']

        assert "extensions" not in extract_materials(gltf_1)[-1]
        assert "extensions" in extract_materials(gltf_2)[-1]

    def test_primitive_geometry_meta(self):
        # Model with primitives
        s = g.get_mesh('CesiumMilkTruck.glb')

        # Assert that primitive geometries are marked as such
        assert s.geometry['Cesium_Milk_Truck_0'].metadata['from_gltf_primitive']

        # Assert that geometries that are not primitives are not marked as such
        assert not s.geometry['Wheels'].metadata['from_gltf_primitive']

    def test_points(self):
        # test a simple pointcloud export-import cycle
        points = g.np.arange(30).reshape((-1, 3))
        export = g.trimesh.Scene(
            g.trimesh.PointCloud(points)).export(file_type='glb')
        validate_glb(export)
        reloaded = g.trimesh.load(
            g.trimesh.util.wrap_as_stream(export),
            file_type='glb')
        # make sure points survived export and reload
        assert g.np.allclose(next(iter(reloaded.geometry.values())).vertices, points)

    def test_bulk(self):
        # Try exporting every loadable model to GLTF and checking
        # the generated header against the schema.

        # strict mode runs a schema header validation
        assert g.trimesh.tol.strict

        # check mesh, path, pointcloud exports
        for root in [g.dir_models, g.os.path.join(g.dir_models, '2D')]:
            for fn in g.os.listdir(root):
                path_in = g.os.path.join(root, fn)
                try:
                    geom = g.trimesh.load(path_in)
                    if isinstance(geom, g.trimesh.path.path.Path):
                        geom = g.trimesh.Scene(geom)
                except BaseException as E:
                    print(E)
                    continue
                # voxels don't have an export to gltf mode
                if not hasattr(geom, 'export'):
                    continue
                elif hasattr(geom, 'vertices') and len(geom.vertices) == 0:
                    continue
                elif hasattr(geom, 'geometry') and len(geom.geometry) == 0:
                    continue

                g.log.info('Testing: {}'.format(fn))
                # check a roundtrip which will validate on export
                # and crash on reload if we've done anything screwey
                export = geom.export(file_type='glb')
                validate_glb(export)
                # todo : importer breaks on `models/empty*` as it
                # doesn't know what to do with empty meshes
                # reloaded = g.trimesh.load(
                #    g.trimesh.util.wrap_as_stream(export),
                #    file_type='glb')


if __name__ == '__main__':
    g.trimesh.util.attach_to_log()
    g.unittest.main()
