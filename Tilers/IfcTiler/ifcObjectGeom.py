# -*- coding: utf-8 -*-
import sys
import numpy as np
from py3dtiles import BoundingVolumeBox, TriangleSoup
from Tilers.object_to_tile import ObjectToTile, ObjectsToTile
import ifcopenshell

import os
from os import listdir
from os.path import isfile, join
from pyproj import Transformer

def normalize(v): 
    norm = np.linalg.norm(v) 
    if norm == 0: 
        return v 
    return v / norm

def computeDirection(axis,refDirection):
    # ref to https://standards.buildingsmart.org/IFC/RELEASE/IFC2x3/FINAL/HTML/ifcgeometryresource/lexical/ifcfirstprojaxis.htm
    # and https://standards.buildingsmart.org/IFC/RELEASE/IFC2x3/FINAL/HTML/ifcgeometryresource/lexical/ifcbuildaxes.htm
    Z = normalize(axis)
    V = normalize(refDirection)
    XVec = np.multiply(np.dot(V, Z), Z)
    XAxis = normalize(np.subtract(V,XVec))
    return np.array([XAxis,np.cross(Z,XAxis),Z])

def unitConversion(originalUnit,targetedUnit):
    conversions = {
                "mm": {"mm": 1, "cm": 1/10, "m": 1/1000, "km": 1/1000000},
                "cm": {"mm": 10, "cm": 1, "m": 1/100, "km": 1/100000},
                "m":  {"mm": 1000, "cm": 100, "m": 1, "km": 1/1000},
                "km": {"mm": 100000, "cm": 10000, "m": 1000, "km": 1},
              }
    return conversions[originalUnit][targetedUnit]

class IfcObjectGeom(ObjectToTile):
    def __init__(self,ifcObject,originalUnit = "m",targetedUnit = "m"):
        super().__init__()

        self.id = ifcObject.GlobalId
        self.geom = TriangleSoup()
        self.ifcObject = ifcObject
        self.ifcClasse = ifcObject.is_a()
        self.convertionRatio = unitConversion(originalUnit,targetedUnit)
        self.has_geom = self.parse_geom()

    def hasGeom(self):
        return self.has_geom

    def get_geom_as_triangles(self):
        return self.geom.triangles[0]

    def set_triangles(self,triangles):
        self.geom.triangles[0] = triangles

    def computeCenter(self,pointList) :
        center = np.array([0.0,0.0,0.0])
        for point in pointList :
            center += np.array([point[0],point[1],0])
        return center / len(pointList)

    def getIfcClasse(self) :
        return self.ifcClasse

    def extrudGeom(self,geom) :
        depth = geom.Depth
        extrudedDirection = geom.ExtrudedDirection.DirectionRatios
        extrudVector = np.multiply(extrudedDirection,depth)

        position = geom.Position.Location.Coordinates

        axis = [0,0,1]
        refDirection = [1,0,0]

        if (geom.Position.Axis) :
            axis = geom.Position.Axis.DirectionRatios
        
        if (geom.Position.RefDirection) :
            refDirection = geom.Position.RefDirection.DirectionRatios 

        direction = computeDirection(axis,refDirection)
        
        points = geom.SweptArea.OuterCurve.Points.CoordList
        center = self.computeCenter(points)
        
        vertexList = list()
        indexList = list()
        for point in points : 
            vertexList.append(np.array([point[0],point[1],0]))
        for point in points : 
            vertexList.append(np.array([point[0],point[1],0]) + extrudVector)    
        vertexList.append(center)            
        vertexList.append(center + extrudVector)

        for i in range(len(vertexList)) : 
            vertexList[i] = np.dot(np.array(vertexList[i]),direction) + position

        nb_points = len(points)
        i = 0
        for i in range(nb_points - 1) :
            indice = i+1
            indexList.append([indice,(nb_points * 2) + 1,indice + 1])
            indexList.append([indice + nb_points,indice + nb_points + 1,(nb_points * 2) + 2])
        
        i = 0
        for i in range(nb_points - 1) :
            indice = i+1
            indexList.append([indice,indice + 1,indice + nb_points ])
            indexList.append([indice + 1,indice + nb_points + 1,indice + nb_points])

        return vertexList, indexList

    def getPosition(self,ObjectPlacement) :
        listPosition = list()
        position = np.array(ObjectPlacement.RelativePlacement.Location.Coordinates)
        listPosition.append(position)
        placementRelTo = ObjectPlacement.PlacementRelTo
        
        while (placementRelTo) :
            if(placementRelTo.PlacesObject[0].is_a("IfcSite")):
                break
            listPosition.append(np.array(placementRelTo.RelativePlacement.Location.Coordinates))
            placementRelTo = placementRelTo.PlacementRelTo
        return listPosition

    def getDirections(self,ObjectPlacement) :
        listDirection = list()
        axis = [0,0,1]
        if (ObjectPlacement.RelativePlacement.Axis) :
            axis = ObjectPlacement.RelativePlacement.Axis.DirectionRatios
        
        refDirection = [1,0,0]
        if (ObjectPlacement.RelativePlacement.RefDirection) :
            refDirection = ObjectPlacement.RelativePlacement.RefDirection.DirectionRatios 

        listDirection.append(computeDirection(axis,refDirection))
        
        placementRelTo = ObjectPlacement.PlacementRelTo
        
        while (placementRelTo) :
            if(placementRelTo.PlacesObject[0].is_a("IfcSite")):
                break
            axis = [0,0,1]
            if (placementRelTo.RelativePlacement.Axis) :
                axis = placementRelTo.RelativePlacement.Axis.DirectionRatios
            
            refDirection = [1,0,0]
            if (placementRelTo.RelativePlacement.RefDirection) :
                refDirection = placementRelTo.RelativePlacement.RefDirection.DirectionRatios 

            listDirection.append(computeDirection(axis,refDirection))
            placementRelTo = placementRelTo.PlacementRelTo

        return listDirection

    def getElevation(self) :
        elevation = 0
        if(self.ifcObject.ContainedInStructure) :
            if(not(self.ifcObject.ContainedInStructure[0].RelatingStructure.is_a("IfcSpace"))) :
                elevation += (self.ifcObject.ContainedInStructure[0].RelatingStructure.Elevation * self.convertionRatio)
        return elevation


    #def parse_indexed_faces(self, Faces):
    # première méthode: triangulation des faces en prenant comme "point pivot" le premier vertex de chaque face
    # exemple : 1,2,3,4,5 deviennent 1,2,3 puis 1,3,4 et 1,4,5
    def parse_indexed_faces(self, Faces):
        
        indexListTemp = list()

        for face in Faces:
            for i in range(1,len(face.CoordIndex)-1):    
                indexListTemp.append([face.CoordIndex[0],face.CoordIndex[i],face.CoordIndex[i+1]])
        
        return indexListTemp

    def parse_geom(self):
        if (not(self.ifcObject.Representation)) :
            return False
        
        representations = self.ifcObject.Representation.Representations
            
        listPosition = self.getPosition(self.ifcObject.ObjectPlacement)

        listDirection = self.getDirections(self.ifcObject.ObjectPlacement)

        
        vertexList = list()
        indexList = list()
        for representation in representations :
            if(representation.RepresentationType == "MappedRepresentation") :
                representation = representation.Items[0].MappingSource.MappedRepresentation

            nb_geom = 0
            for itemGeom in representation.Items :
                nb_geom += 1
                if(nb_geom > 300) :
                    continue
                indexListTemp = None
                vertexListTemp = None
                if(representation.RepresentationType == "Tessellation") :
                    if( hasattr(itemGeom, 'Faces')) :
                        indexListTemp=self.parse_indexed_faces(itemGeom.Faces)
                    elif (hasattr(itemGeom, 'CoordIndex')):
                        indexListTemp = itemGeom.CoordIndex
                    else :
                            sys.exit("Géométrie de ce type non encore gérée")
                    vertexListTemp = itemGeom.Coordinates.CoordList

                elif(representation.RepresentationType == "SweptSolid") :
                    vertexListTemp,indexListTemp = self.extrudGeom(itemGeom)
                if(vertexListTemp and indexListTemp) :
                    for index in indexListTemp :
                        indexList.append([index[0]+len(vertexList),index[1]+len(vertexList),index[2]+len(vertexList)])
                    for vertex in vertexListTemp:
                        vertexList.append(np.array([vertex[0],vertex[1],vertex[2]],dtype=np.float32))


        if (len(indexList) == 0) :
            return False

        for j in range(len(vertexList)):
            vertex = vertexList[j]
            for i in range(len(listDirection)) :
                vertex = np.dot(np.array(vertex),listDirection[i])
                vertex = (vertex + listPosition[i])
                vertex = vertex * self.convertionRatio
            vertexList[j] = np.array([round(vertex[0],5),round(vertex[1],5),round(vertex[2],5)],dtype=np.float32)

        triangles = list()
        for index in indexList:
            triangle = []
            for i in range(0,3): 
                # We store each position for each triangles, as GLTF expect
                triangle.append(vertexList[index[i] - 1])
            triangles.append(triangle)
        
        self.geom.triangles.append(triangles)

        self.set_box()

        return True
    
    def set_box(self):
        """
        Parameters
        ----------
        Returns
        -------
        """
        bbox = self.geom.getBbox()
        self.box = BoundingVolumeBox()
        self.box.set_from_mins_maxs(np.append(bbox[0],bbox[1]))
        
        # Set centroid from Bbox center
        self.centroid = np.array([(bbox[0][0] + bbox[1][0]) / 2.0,
                         (bbox[0][1] + bbox[1][1]) / 2.0,
                         (bbox[0][2] + bbox[0][2]) / 2.0])

    def get_obj_id(self):
        return super().get_id()
    
    def set_obj_id(self,id):
        return super().set_id(id)

class IfcObjectsGeom(ObjectsToTile):
    """
        A decorated list of ObjectsToTile type objects.
    """
    def __init__(self,objs=None):
        super().__init__(objs)

    @staticmethod
    def computeCentroid(ifcSite,unitRatio) :
        elevation = ifcSite.RefElevation
        placement = ifcSite.ObjectPlacement.RelativePlacement
        location = placement.Location.Coordinates
        location = (location[0] * unitRatio,location[1] * unitRatio,(location[2] + elevation) * unitRatio)

        # transformer = Transformer.from_crs("EPSG:27562", "EPSG:3946")
        transformer = Transformer.from_crs("EPSG:3947", "EPSG:3857")
        location = transformer.transform(location[0],location[1],location[2])

        if(placement.Axis==None):
            axis = [0,0,1]
        else :
            axis = placement.Axis.DirectionRatios
        if(placement.RefDirection==None):
             refDirection = [1,0,0]
        else:
            refDirection = placement.RefDirection.DirectionRatios

        direction = computeDirection(axis,refDirection)
        centroid = [direction[0][0],direction[0][1],direction[0][2],0,
                    direction[1][0],direction[1][1],direction[1][2],0,
                    direction[2][0],direction[2][1],direction[2][2],0,
                    location[0],location[1],location[2],1]
        return centroid


    @staticmethod
    def retrievObjByType(path_to_file,originalUnit = "m",targetedUnit = "m"):
        """
        :param path: a path to a directory

        :return: a list of Obj. 
        """
        ifc_file = ifcopenshell.open(path_to_file)
        
        centroid = IfcObjectsGeom.computeCentroid(ifc_file.by_type('IfcSite')[0],unitConversion(originalUnit,targetedUnit))
        elements = ifc_file.by_type('IfcElement')   

        dictObjByType = dict()
        for element in elements:
            if not(element.is_a() in dictObjByType):
                print(element.is_a())
                dictObjByType[element.is_a()] = list()   

            obj = IfcObjectGeom(element,originalUnit,targetedUnit)
            if(obj.hasGeom()):
                dictObjByType[element.is_a()].append(obj)

        for key in dictObjByType.keys():
            dictObjByType[key] = IfcObjectsGeom(dictObjByType[key])

        return dictObjByType, centroid
   
